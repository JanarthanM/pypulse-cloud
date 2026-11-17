import ast
from dataclasses import dataclass, asdict
from typing import Dict, List, Set, Tuple, Any


@dataclass
class FunctionMetrics:
    name: str
    qualified_name: str
    file_path: str
    line_no: int
    args_count: int
    loc: int
    cyclomatic_complexity: int
    has_type_hints: bool
    calls: List[str]
    is_dead_code: bool = False
    risk_level: str = "LOW"


@dataclass
class CodeSmell:
    file_path: str
    line_no: int
    rule: str
    severity: str
    message: str


class SourceASTVisitor(ast.NodeVisitor):
    def __init__(self, module_name: str, file_path: str):
        self.module_name = module_name
        self.file_path = file_path
        self.functions: List[FunctionMetrics] = []
        self.smells: List[CodeSmell] = []
        self.imports: Set[str] = set()
        self.global_calls: Set[str] = set()
        self._current_func: FunctionMetrics | None = None
        self._current_class: str | None = None

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.add(alias.name.split(".")[0])
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module and node.level == 0:
            self.imports.add(node.module.split(".")[0])
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        prev = self._current_class
        self._current_class = node.name
        self.generic_visit(node)
        self._current_class = prev

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is None:
            self.smells.append(CodeSmell(
                file_path=self.file_path,
                line_no=node.lineno,
                rule="BARE_EXCEPT",
                severity="HIGH",
                message="Bare 'except:' catches SystemExit/KeyboardInterrupt; specify an exception class."
            ))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._process_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._process_function(node)

    def _process_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        complexity = self._compute_complexity(node)
        end_line = getattr(node, "end_lineno", node.lineno)
        loc = max(1, end_line - node.lineno + 1)
        prefix = f"{self.module_name}.{self._current_class}" if self._current_class else self.module_name

        # Check mutable default arguments (list, dict, set literals)
        for default in node.args.defaults + node.args.kw_defaults:
            if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                self.smells.append(CodeSmell(
                    file_path=self.file_path,
                    line_no=node.lineno,
                    rule="MUTABLE_DEFAULT_ARG",
                    severity="HIGH",
                    message=f"Function '{node.name}' uses a mutable default argument; use None instead."
                ))

        # Check loop nesting depth >= 3
        max_loop_depth = self._max_loop_depth(node)
        if max_loop_depth >= 3:
            self.smells.append(CodeSmell(
                file_path=self.file_path,
                line_no=node.lineno,
                rule="DEEP_LOOP_NESTING",
                severity="MEDIUM",
                message=f"Function '{node.name}' has {max_loop_depth}-level nested loops (O(n^{max_loop_depth}) risk)."
            ))

        # Check type hint presence
        non_self_args = [a for a in node.args.args if a.arg not in ("self", "cls")]
        has_hints = bool(node.returns) or any(a.annotation is not None for a in non_self_args)

        risk = "HIGH" if (complexity >= 12 or loc > 60) else ("MEDIUM" if (complexity >= 6 or loc > 30) else "LOW")

        metrics = FunctionMetrics(
            name=node.name,
            qualified_name=f"{prefix}.{node.name}",
            file_path=self.file_path,
            line_no=node.lineno,
            args_count=len(node.args.args),
            loc=loc,
            cyclomatic_complexity=complexity,
            has_type_hints=has_hints,
            calls=[],
            risk_level=risk,
        )

        prev = self._current_func
        self._current_func = metrics
        self.generic_visit(node)
        self._current_func = prev
        self.functions.append(metrics)

    def visit_Call(self, node: ast.Call) -> None:
        name = node.func.id if isinstance(node.func, ast.Name) else (node.func.attr if isinstance(node.func, ast.Attribute) else None)
        if name:
            if self._current_func:
                self._current_func.calls.append(name)
            else:
                self.global_calls.add(name)
        self.generic_visit(node)

    @staticmethod
    def _compute_complexity(node: ast.AST) -> int:
        branches = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.With, ast.AsyncWith, ast.IfExp, ast.comprehension)
        score = 1
        for child in ast.walk(node):
            if isinstance(child, branches):
                score += 1
            elif isinstance(child, ast.BoolOp):
                score += len(child.values) - 1
        return score

    def _max_loop_depth(self, node: ast.AST, depth: int = 0) -> int:
        max_d = depth
        for child in ast.iter_child_nodes(node):
            next_d = depth + 1 if isinstance(child, (ast.For, ast.AsyncFor, ast.While)) else depth
            max_d = max(max_d, self._max_loop_depth(child, next_d))
        return max_d


def analyze_sources(files: Dict[str, str]) -> Dict[str, Any]:
    ENTRY_PREFIXES = ("test_", "main", "cli", "app", "run", "setup", "get_", "post_", "handle_")
    all_functions: List[FunctionMetrics] = []
    all_smells: List[CodeSmell] = []
    import_graph: Dict[str, Set[str]] = {}
    all_called_names: Set[str] = set()
    local_modules = {path.rsplit("/", 1)[-1].replace(".py", "") for path in files}

    for path, source in files.items():
        mod_name = path.rsplit("/", 1)[-1].replace(".py", "")
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue

        visitor = SourceASTVisitor(module_name=mod_name, file_path=path)
        visitor.visit(tree)

        all_functions.extend(visitor.functions)
        all_smells.extend(visitor.smells)
        import_graph[mod_name] = visitor.imports.intersection(local_modules) - {mod_name}
        all_called_names.update(visitor.global_calls)
        for fn in visitor.functions:
            all_called_names.update(fn.calls)

    dead_functions = []
    for fn in all_functions:
        is_dunder = fn.name.startswith("__") and fn.name.endswith("__")
        is_entry = fn.name.startswith(ENTRY_PREFIXES)
        if not is_dunder and not is_entry and fn.name not in all_called_names:
            fn.is_dead_code = True
            dead_functions.append(fn)

    cycles: List[List[str]] = []
    visited: Set[str] = set()

    def dfs(node: str, path: List[str]) -> None:
        if node in path:
            cycle = path[path.index(node):] + [node]
            if cycle not in cycles:
                cycles.append(cycle)
            return
        if node in visited:
            return
        visited.add(node)
        for nbr in import_graph.get(node, set()):
            dfs(nbr, path + [node])

    for mod in import_graph:
        dfs(mod, [])

    edges: List[Tuple[str, str]] = [
        (src, dst) for src, targets in import_graph.items() for dst in targets
    ]

    typed_count = sum(1 for f in all_functions if f.has_type_hints)
    type_coverage = round((typed_count / len(all_functions)) * 100, 1) if all_functions else 100.0
    avg_cc = (sum(f.cyclomatic_complexity for f in all_functions) / len(all_functions)) if all_functions else 1.0
    dead_ratio = (len(dead_functions) / len(all_functions)) if all_functions else 0.0
    penalty = (avg_cc * 2.2) + (dead_ratio * 30) + (len(cycles) * 10) + (len(all_smells) * 2.5)
    health_score = max(0, min(100, round(100 - penalty)))

    return {
        "files_scanned": len(files),
        "total_functions": len(all_functions),
        "avg_complexity": round(avg_cc, 2),
        "type_coverage": type_coverage,
        "health_score": health_score,
        "dead_code_count": len(dead_functions),
        "smells_count": len(all_smells),
        "circular_imports": cycles,
        "import_edges": edges,
        "modules": sorted(list(local_modules)),
        "all_functions": [asdict(f) for f in sorted(all_functions, key=lambda x: x.cyclomatic_complexity, reverse=True)],
        "dead_functions": [asdict(f) for f in dead_functions],
        "code_smells": [asdict(s) for s in all_smells],
    }

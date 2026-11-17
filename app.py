import asyncio
import re
from typing import Dict
import httpx
import pandas as pd
import streamlit as st
from analyzer import analyze_sources

st.set_page_config(
    page_title="PyPulse | Python AST Codebase Auditor",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Custom SaaS Styling ---
st.markdown("""
<style>
    .block-container { padding-top: 1.8rem; padding-bottom: 2rem; }
    .hero-box {
        background: linear-gradient(135deg, #111827 0%, #064E3B 100%);
        border: 1px solid #10B98144;
        border-radius: 14px;
        padding: 1.5rem 2rem;
        margin-bottom: 1.5rem;
    }
    .hero-title {
        font-size: 2rem;
        font-weight: 800;
        color: #F9FAFB;
        margin: 0;
        letter-spacing: -0.5px;
    }
    .hero-sub {
        color: #A7F3D0;
        font-size: 0.98rem;
        margin-top: 0.35rem;
    }
    div[data-testid="stMetric"] {
        background-color: #111827;
        border: 1px solid #1F2937;
        border-radius: 12px;
        padding: 1rem 1.1rem;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
    }
    div[data-testid="stMetricLabel"] { color: #9CA3AF; font-size: 0.85rem; }
    div[data-testid="stMetricValue"] { color: #F9FAFB; font-weight: 700; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] {
        background-color: #111827;
        border-radius: 8px 8px 0 0;
        padding: 0.5rem 1.1rem;
        border: 1px solid #1F2937;
    }
</style>
""", unsafe_allow_html=True)


async def fetch_github_python_files(repo_url: str, max_files: int = 35) -> Dict[str, str]:
    match = re.search(r"github\.com/([^/]+)/([^/]+)", repo_url.strip().rstrip("/"))
    if not match:
        raise ValueError("Enter a valid GitHub URL like https://github.com/owner/repo")

    owner, repo = match.group(1), match.group(2).replace(".git", "")
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "PyPulse-Auditor"}

    async with httpx.AsyncClient(timeout=15.0, headers=headers, follow_redirects=True) as client:
        repo_resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}")
        if repo_resp.status_code != 200:
            raise ValueError(f"GitHub API Error ({repo_resp.status_code}): Check if the repo is public.")
        default_branch = repo_resp.json().get("default_branch", "main")

        tree_resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/git/trees/{default_branch}?recursive=1"
        )
        tree_data = tree_resp.json().get("tree", [])
        py_paths = [
            item["path"] for item in tree_data
            if item["type"] == "blob" and item["path"].endswith(".py")
        ][:max_files]

        if not py_paths:
            raise ValueError("No Python (.py) files found in this repository.")

        async def download_file(path: str):
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{default_branch}/{path}"
            r = await client.get(raw_url)
            return path, r.text if r.status_code == 200 else ""

        results = await asyncio.gather(*(download_file(p) for p in py_paths))
        return {path: code for path, code in results if code}


def build_markdown_report(target_name: str, report: dict) -> str:
    lines = [
        f"# PyPulse AST Audit Report: `{target_name}`",
        "",
        f"- **Health Score:** {report['health_score']}/100",
        f"- **Files Scanned:** {report['files_scanned']}",
        f"- **Total Functions:** {report['total_functions']}",
        f"- **Avg Cyclomatic Complexity:** {report['avg_complexity']}",
        f"- **Type-Hint Coverage:** {report['type_coverage']}%",
        f"- **Code Smells Flagged:** {report['smells_count']}",
        f"- **Dead Functions:** {report['dead_code_count']}",
        "",
        "## Top Complexity Hotspots",
    ]
    for fn in report["all_functions"][:10]:
        lines.append(
            f"- `{fn['qualified_name']}` (`{fn['file_path']}:{fn['line_no']}`) — CC: **{fn['cyclomatic_complexity']}** | Risk: **{fn['risk_level']}**"
        )
    if report["code_smells"]:
        lines.extend(["", "## Anti-Patterns & Code Smells"])
        for s in report["code_smells"]:
            lines.append(f"- **[{s['severity']}] {s['rule']}** (`{s['file_path']}:{s['line_no']}`): {s['message']}")
    return "\n".join(lines)


# --- Sidebar Controls ---
with st.sidebar:
    st.markdown("### Audit Settings")
    mode = st.radio("Input Source", ["Public GitHub Repository", "Paste Python Code"])
    max_files = st.slider("Max Python Files to Scan", min_value=5, max_value=60, value=30, step=5)
    st.divider()
    st.markdown("**Quick Demo Repos**")
    if st.button("Scan PhishLens (Your Repo)", use_container_width=True):
        st.session_state["repo_input"] = "https://github.com/JanarthanM/phishlens"
    if st.button("Scan PSF / Requests", use_container_width=True):
        st.session_state["repo_input"] = "https://github.com/psf/requests"
    if st.button("Scan Tiangolo / FastAPI", use_container_width=True):
        st.session_state["repo_input"] = "https://github.com/fastapi/fastapi"
    st.divider()
    st.caption("Built with Python `ast`, `asyncio`, `httpx` & Streamlit.")

# --- Hero Banner ---
st.markdown("""
<div class="hero-box">
    <div class="hero-title">⚡ PyPulse — Python AST Codebase Auditor</div>
    <div class="hero-sub">Static Abstract Syntax Tree analysis for Cyclomatic Complexity, Anti-Patterns, Dead Code & Module Dependencies</div>
</div>
""", unsafe_allow_html=True)

if "repo_input" not in st.session_state:
    st.session_state["repo_input"] = "https://github.com/JanarthanM/phishlens"

sources: Dict[str, str] = {}
target_label = "snippet.py"

if mode == "Public GitHub Repository":
    col_in, col_btn = st.columns([5, 1])
    with col_in:
        repo_url = st.text_input(
            "GitHub Repository URL",
            value=st.session_state["repo_input"],
            label_visibility="collapsed",
            placeholder="https://github.com/owner/repository",
        )
    with col_btn:
        run_clicked = st.button("Run Audit", type="primary", use_container_width=True)

    target_label = repo_url
    if run_clicked:
        with st.spinner("Fetching Python modules concurrently & traversing AST..."):
            try:
                sources = asyncio.run(fetch_github_python_files(repo_url, max_files=max_files))
            except Exception as exc:
                st.error(str(exc))
else:
    sample_code = '''def legacy_unused_helper(x=[]):
    try:
        return sum(x)
    except:
        return 0

def process_orders(orders: list) -> float:
    total = 0.0
    for o in orders:
        if o.get("status") == "PAID":
            if o.get("priority") and o.get("amount") > 500:
                total += o["amount"] * 0.9
            elif o.get("coupon"):
                total += o["amount"] * 0.95
            else:
                total += o["amount"]
    return total
'''
    pasted = st.text_area("Paste Python Source Code", value=sample_code, height=220)
    if st.button("Analyze Snippet", type="primary"):
        sources = {"snippet.py": pasted}

# --- Results Dashboard ---
if sources:
    report = analyze_sources(sources)
    score = report["health_score"]

    # Health Score Bar + Export Button
    h_col1, h_col2 = st.columns([4, 1])
    with h_col1:
        grade = "Excellent" if score >= 80 else ("Moderate Debt" if score >= 55 else "Needs Refactoring")
        st.markdown(f"**Overall Maintainability Score: {score}/100 ({grade})**")
        st.progress(score / 100)
    with h_col2:
        st.download_button(
            label="Export Audit (.md)",
            data=build_markdown_report(target_label, report),
            file_name="PYPULSE_AUDIT.md",
            mime="text/markdown",
            use_container_width=True,
        )

    st.write("")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Health Score", f"{score}/100")
    c2.metric("Python Files", report["files_scanned"])
    c3.metric("Functions", report["total_functions"])
    c4.metric("Avg Complexity", report["avg_complexity"])
    c5.metric("Type Hints", f"{report['type_coverage']}%")
    c6.metric("Dead Functions", report["dead_code_count"])

    if report["circular_imports"]:
        st.error(f"Circular Import Chains Detected: {report['circular_imports']}")
    else:
        st.success("Architecture Check Passed: Zero circular imports across scanned modules.")

    st.write("")
    tab1, tab2, tab3, tab4 = st.tabs([
        "Complexity Hotspots",
        f"Code Smells ({report['smells_count']})",
        "Dependency Graph",
        f"Dead Code ({report['dead_code_count']})",
    ])

    with tab1:
        if report["all_functions"]:
            df = pd.DataFrame(report["all_functions"])[
                ["qualified_name", "file_path", "line_no", "cyclomatic_complexity", "loc", "has_type_hints", "risk_level"]
            ]
            top_chart = df.head(10).set_index("qualified_name")["cyclomatic_complexity"]
            st.caption("Top 10 Most Complex Functions (McCabe Score)")
            st.bar_chart(top_chart, color="#10B981", height=240)

            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "qualified_name": "Function / Method",
                    "file_path": "File",
                    "line_no": st.column_config.NumberColumn("Line", format="%d"),
                    "cyclomatic_complexity": st.column_config.ProgressColumn(
                        "Complexity", min_value=1, max_value=20, format="%d"
                    ),
                    "loc": st.column_config.NumberColumn("Lines", format="%d"),
                    "has_type_hints": st.column_config.CheckboxColumn("Typed"),
                    "risk_level": "Risk",
                },
            )

    with tab2:
        if report["code_smells"]:
            smells_df = pd.DataFrame(report["code_smells"])
            st.dataframe(smells_df, use_container_width=True, hide_index=True)
        else:
            st.info("Clean scan: No mutable default arguments, bare excepts, or deep nested loops found.")

    with tab3:
        if report["import_edges"]:
            dot_lines = [
                "digraph G {",
                '  bgcolor="transparent";',
                '  rankdir=LR;',
                '  node [shape=box, style="rounded,filled", fillcolor="#1F2937", color="#10B981", fontcolor="#F9FAFB", fontname="Sans-Serif"];',
                '  edge [color="#6B7280"];',
            ]
            for src, dst in report["import_edges"]:
                dot_lines.append(f'  "{src}" -> "{dst}";')
            dot_lines.append("}")
            st.graphviz_chart("\n".join(dot_lines))
        else:
            st.info("No internal cross-module imports found in the scanned files.")

    with tab4:
        if report["dead_functions"]:
            dead_df = pd.DataFrame(report["dead_functions"])[["qualified_name", "file_path", "line_no", "loc"]]
            st.dataframe(dead_df, use_container_width=True, hide_index=True)
        else:
            st.info("No unreachable internal functions detected.")

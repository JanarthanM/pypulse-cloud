# PyPulse Cloud — How to Run

## 1. Clone the Repository
```bash
git clone https://github.com/JanarthanM/pypulse-cloud.git
cd pypulse-cloud
```

## 2. Create & Activate a Virtual Environment

**Windows (PowerShell):**
```powershell
python -m venv .venv
..\.venv\Scripts\Activate.ps1
```

**Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

## 3. Install Dependencies
```bash
pip install -r requirements.txt
```

## 4. Start the Application
```bash
streamlit run app.py
```

Open `http://localhost:8501` in your browser.

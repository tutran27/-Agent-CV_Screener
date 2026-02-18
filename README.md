### 🧠 CV_Screener  
AI-Powered Resume Screening System with Human-in-the-Loop Review

---

### 🚀 Overview
CV_Screener is an AI-driven backend system that automates resume screening using LLMs and a structured LangGraph workflow, while ensuring human approval before final decisions.

---

### ⚙️ Core Features
- 📄 Extract structured data from raw CV text (LLM-based)
- 📊 Score candidates using a weighted rubric
- 🚩 Flag missing skills or incomplete information
- 👨‍⚖️ Require human review before final decision
- 💾 Persist results in SQLite database

---

### 🏗 Architecture
Submit CV  
→ LLM Extraction  
→ Scoring  
→ Flag Detection  
→ Human Review (Interrupt)  
→ Finalize & Persist  

Built with:
- FastAPI (API layer)
- LangGraph (workflow engine)
- Groq LLaMA (LLM)
- SQLite (database)

---

### 📊 Scoring Logic
- Required Skills — 60%
- Nice-to-have Skills — 30%
- Experience — 10%

Final score normalized to 0–100.

---

### 🔒 Ethical AI Design
The system only evaluates job-relevant information and avoids extracting sensitive attributes (age, gender, religion, etc.).

---

### ▶️ Run Locally

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```env
GROQ_API_KEY=your_groq_api_key_here
```

Get your Groq API key from:
https://console.groq.com/

Run the server:

```bash
uvicorn app:app --reload
```

Swagger Docs:
http://127.0.0.1:8000/docs


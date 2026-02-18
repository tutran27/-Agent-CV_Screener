import sqlite3, json, time
from typing import Optional, Dict, Any

DB_PATH = "recruiting.sqlite"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        application_id TEXT UNIQUE,
        cv_text TEXT,
        extracted_json TEXT,
        score INTEGER,
        flags_json TEXT,
        decision TEXT,
        reviewer_notes TEXT,
        created_at REAL,
        updated_at REAL
    )
    """)
    conn.commit()
    conn.close()

def upsert_application(application_id: str, cv_text: str) -> Dict[str, Any]:

    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now = time.time()
    
    # Cập nhật: Thêm đoạn reset các cột kết quả về NULL
    cur.execute("""
        INSERT INTO applications(application_id, cv_text, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(application_id) DO UPDATE SET
            cv_text=excluded.cv_text,
            updated_at=excluded.updated_at,
            extracted_json=NULL,
            score=NULL,
            flags_json=NULL,
            decision=NULL,
            reviewer_notes=NULL
    """, (application_id, cv_text, now, now))
    
    conn.commit()
    
    # Lấy lại ID và decision (lúc này decision sẽ là None)
    cur.execute("SELECT id, decision FROM applications WHERE application_id=?", (application_id,))
    row = cur.fetchone()
    conn.close()
    
    return {"ok": True, "db_id": row[0], "decision": row[1]}
def update_analysis(application_id: str, extracted: dict, score: int, flags: list) -> Dict[str, Any]:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now = time.time()
    cur.execute("""
        UPDATE applications
        SET extracted_json=?, score=?, flags_json=?, updated_at=?
        WHERE application_id=?
    """, (json.dumps(extracted, ensure_ascii=False), score, json.dumps(flags, ensure_ascii=False), now, application_id))
    conn.commit()
    conn.close()
    return {"ok": True}

def set_decision(application_id: str, decision: str, reviewer_notes: str = "") -> Dict[str, Any]:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now = time.time()
    cur.execute("""
        UPDATE applications
        SET decision=?, reviewer_notes=?, updated_at=?
        WHERE application_id=?
    """, (decision, reviewer_notes, now, application_id))
    conn.commit()
    conn.close()
    return {"ok": True}

def get_application(application_id: str) -> Optional[dict]:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT application_id, cv_text, extracted_json, score, flags_json, decision, reviewer_notes
        FROM applications WHERE application_id=?
    """, (application_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "application_id": row[0],
        "cv_text": row[1],
        "extracted_json": json.loads(row[2]) if row[2] else None,
        "score": row[3],
        "flags": json.loads(row[4]) if row[4] else [],
        "decision": row[5],
        "reviewer_notes": row[6],
    }

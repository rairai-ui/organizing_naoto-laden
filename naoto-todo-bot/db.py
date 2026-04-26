import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

DATA_DIR = os.getenv("DATA_DIR", ".")
DB_PATH = Path(DATA_DIR) / "naoto.db"


def init_db():
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                summary TEXT,
                source_filename TEXT,
                chroma_id TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS todos (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'pending',
                priority TEXT DEFAULT 'medium',
                due_date DATE,
                memory_id TEXT,
                completed_at DATETIME,
                completion_note TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


@contextmanager
def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def create_memory(type_, content, summary=None, source_filename=None, chroma_id=None):
    mid = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO memories (id, type, content, summary, source_filename, chroma_id) VALUES (?, ?, ?, ?, ?, ?)",
            (mid, type_, content, summary, source_filename, chroma_id),
        )
    return mid


def set_memory_chroma_id(memory_id, chroma_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE memories SET chroma_id = ? WHERE id = ?",
            (chroma_id, memory_id),
        )


def get_memories_by_ids(ids):
    if not ids:
        return []
    with get_conn() as conn:
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT * FROM memories WHERE id IN ({placeholders})", list(ids)
        ).fetchall()
        return [dict(r) for r in rows]


def create_todo(title, description=None, priority="medium", due_date=None, memory_id=None, status="pending"):
    tid = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO todos (id, title, description, status, priority, due_date, memory_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (tid, title, description, status, priority, due_date, memory_id),
        )
        row = conn.execute("SELECT * FROM todos WHERE id = ?", (tid,)).fetchone()
        return dict(row)


def list_todos(status=None, priority=None):
    sql = "SELECT * FROM todos WHERE 1=1"
    params = []
    if status:
        sql += " AND status = ?"
        params.append(status)
    if priority:
        sql += " AND priority = ?"
        params.append(priority)
    sql += " ORDER BY (due_date IS NULL), due_date ASC, created_at DESC"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def get_todo(id_):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM todos WHERE id = ?", (id_,)).fetchone()
        return dict(row) if row else None


def update_todo(id_, **fields):
    allowed = {"title", "description", "status", "priority", "due_date"}
    sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not sets:
        return get_todo(id_)
    cols = ", ".join(f"{k} = ?" for k in sets)
    params = list(sets.values()) + [id_]
    with get_conn() as conn:
        conn.execute(f"UPDATE todos SET {cols} WHERE id = ?", params)
        row = conn.execute("SELECT * FROM todos WHERE id = ?", (id_,)).fetchone()
        return dict(row) if row else None


def delete_todo(id_):
    with get_conn() as conn:
        conn.execute("DELETE FROM todos WHERE id = ?", (id_,))


def complete_todo(id_, completion_note=None):
    with get_conn() as conn:
        conn.execute(
            "UPDATE todos SET status = 'done', completed_at = CURRENT_TIMESTAMP, completion_note = ? WHERE id = ?",
            (completion_note, id_),
        )
        row = conn.execute("SELECT * FROM todos WHERE id = ?", (id_,)).fetchone()
        return dict(row) if row else None

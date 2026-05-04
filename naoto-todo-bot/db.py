import os
import uuid
from contextlib import contextmanager

DATABASE_URL = os.getenv("DATABASE_URL", "")
_USE_PG = bool(DATABASE_URL)

if _USE_PG:
    import psycopg2
    import psycopg2.extras
else:
    import sqlite3
    from pathlib import Path
    DATA_DIR = os.getenv("DATA_DIR", ".")
    DB_PATH = Path(DATA_DIR) / "naoto.db"


def _sql(s):
    """SQLiteは ? 、PostgreSQLは %s"""
    return s.replace("?", "%s") if _USE_PG else s


def init_db():
    with get_conn() as conn:
        _execute(conn, """
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                summary TEXT,
                source_filename TEXT,
                chroma_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        _execute(conn, """
            CREATE TABLE IF NOT EXISTS todos (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'pending',
                priority TEXT DEFAULT 'medium',
                due_date DATE,
                memory_id TEXT,
                completed_at TIMESTAMP,
                completion_note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


@contextmanager
def get_conn():
    if _USE_PG:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def _execute(conn, sql, params=()):
    sql = _sql(sql)
    if _USE_PG:
        with conn.cursor() as cur:
            cur.execute(sql, params)
    else:
        conn.execute(sql, params)


def _fetchone(conn, sql, params=()):
    sql = _sql(sql)
    if _USE_PG:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None
    else:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None


def _fetchall(conn, sql, params=()):
    sql = _sql(sql)
    if _USE_PG:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    else:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def create_memory(type_, content, summary=None, source_filename=None, chroma_id=None):
    mid = str(uuid.uuid4())
    with get_conn() as conn:
        _execute(
            conn,
            "INSERT INTO memories (id, type, content, summary, source_filename, chroma_id) VALUES (?, ?, ?, ?, ?, ?)",
            (mid, type_, content, summary, source_filename, chroma_id),
        )
    return mid


def set_memory_chroma_id(memory_id, chroma_id):
    with get_conn() as conn:
        _execute(conn, "UPDATE memories SET chroma_id = ? WHERE id = ?", (chroma_id, memory_id))


def get_memories_by_ids(ids):
    if not ids:
        return []
    with get_conn() as conn:
        placeholders = ",".join(["?"] * len(ids))
        return _fetchall(conn, f"SELECT * FROM memories WHERE id IN ({placeholders})", list(ids))


def create_todo(title, description=None, priority="medium", due_date=None, memory_id=None, status="pending"):
    tid = str(uuid.uuid4())
    with get_conn() as conn:
        _execute(
            conn,
            "INSERT INTO todos (id, title, description, status, priority, due_date, memory_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (tid, title, description, status, priority, due_date, memory_id),
        )
        return _fetchone(conn, "SELECT * FROM todos WHERE id = ?", (tid,))


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
        return _fetchall(conn, sql, params)


def get_todo(id_):
    with get_conn() as conn:
        return _fetchone(conn, "SELECT * FROM todos WHERE id = ?", (id_,))


def update_todo(id_, **fields):
    allowed = {"title", "description", "status", "priority", "due_date"}
    sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not sets:
        return get_todo(id_)
    cols = ", ".join(f"{k} = ?" for k in sets)
    params = list(sets.values()) + [id_]
    with get_conn() as conn:
        _execute(conn, f"UPDATE todos SET {cols} WHERE id = ?", params)
        return _fetchone(conn, "SELECT * FROM todos WHERE id = ?", (id_,))


def delete_todo(id_):
    with get_conn() as conn:
        _execute(conn, "DELETE FROM todos WHERE id = ?", (id_,))


def complete_todo(id_, completion_note=None):
    with get_conn() as conn:
        _execute(
            conn,
            "UPDATE todos SET status = 'done', completed_at = CURRENT_TIMESTAMP, completion_note = ? WHERE id = ?",
            (completion_note, id_),
        )
        return _fetchone(conn, "SELECT * FROM todos WHERE id = ?", (id_,))

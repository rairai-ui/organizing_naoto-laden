import os
import tempfile
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import db
import vector_store
import gemini_service as ai
from models import TextInput, TodoCreate, TodoUpdate, TodoComplete, ChatRequest

app = FastAPI(title="直人さん専用 TODOボット")

db.init_db()


def _normalize_due(due):
    if isinstance(due, str) and due.strip().lower() in ("null", "none", ""):
        return None
    return due


def _process_text_input(text, type_, source_filename=None):
    summary = ai.summarize(text)
    todos_data = ai.extract_todos(text)

    memory_id = db.create_memory(
        type_=type_,
        content=text,
        summary=summary,
        source_filename=source_filename,
    )

    embedding = ai.embed(text)
    vector_store.add(
        memory_id,
        text,
        embedding,
        metadata={
            "type": type_,
            "summary": summary or "",
            "filename": source_filename or "",
        },
    )
    db.set_memory_chroma_id(memory_id, memory_id)

    todos_created = []
    for t in todos_data or []:
        if not isinstance(t, dict) or not t.get("title"):
            continue
        priority = t.get("priority") or "medium"
        if priority not in ("low", "medium", "high"):
            priority = "medium"
        todo = db.create_todo(
            title=t["title"],
            priority=priority,
            due_date=_normalize_due(t.get("due_date")),
            memory_id=memory_id,
        )
        todos_created.append(todo)

    return memory_id, summary, todos_created


@app.post("/api/input/voice")
async def input_voice(
    file: UploadFile = File(...),
    pdf: Optional[UploadFile] = File(None),
):
    suffix = Path(file.filename or "audio").suffix or ".bin"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_audio:
        tmp_audio.write(await file.read())
        audio_path = tmp_audio.name

    pdf_path = None
    if pdf is not None and (pdf.filename or "").strip():
        pdf_suffix = Path(pdf.filename or "doc.pdf").suffix or ".pdf"
        with tempfile.NamedTemporaryFile(delete=False, suffix=pdf_suffix) as tmp_pdf:
            tmp_pdf.write(await pdf.read())
            pdf_path = tmp_pdf.name

    try:
        try:
            transcription = ai.transcribe(audio_path, pdf_path)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, f"文字起こしエラー: {e}") from e
        if not transcription:
            raise HTTPException(500, "文字起こしに失敗しました")

        memory_id, summary, todos_created = _process_text_input(
            transcription, type_="voice", source_filename=file.filename
        )
        return {
            "memory_id": memory_id,
            "transcription": transcription,
            "summary": summary,
            "todos_created": todos_created,
        }
    finally:
        for p in (audio_path, pdf_path):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass


@app.post("/api/input/text")
async def input_text(payload: TextInput):
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(400, "textが空です")
    memory_id, summary, todos_created = _process_text_input(text, type_="text")
    return {"memory_id": memory_id, "summary": summary, "todos_created": todos_created}


@app.get("/api/todos")
def list_todos(status: Optional[str] = None, priority: Optional[str] = None):
    return db.list_todos(status=status, priority=priority)


@app.post("/api/todos")
def create_todo(payload: TodoCreate):
    return db.create_todo(
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        due_date=_normalize_due(payload.due_date),
    )


@app.patch("/api/todos/{todo_id}")
def update_todo(todo_id: str, payload: TodoUpdate):
    fields = payload.model_dump(exclude_none=True)
    if "due_date" in fields:
        fields["due_date"] = _normalize_due(fields["due_date"])
    todo = db.update_todo(todo_id, **fields)
    if not todo:
        raise HTTPException(404, "todo not found")
    return todo


@app.delete("/api/todos/{todo_id}")
def delete_todo(todo_id: str):
    db.delete_todo(todo_id)
    return {"ok": True}


@app.patch("/api/todos/{todo_id}/complete")
def complete_todo(todo_id: str, payload: TodoComplete):
    existing = db.get_todo(todo_id)
    if not existing:
        raise HTTPException(404, "todo not found")

    todo = db.complete_todo(todo_id, payload.completion_note)
    note = (payload.completion_note or "").strip()
    completion_text = (
        f"【完了報告】{todo['title']}\n{note}" if note else f"【完了報告】{todo['title']}"
    )

    memory_id = db.create_memory(
        type_="completion",
        content=completion_text,
        summary=note or todo["title"],
    )
    embedding = ai.embed(completion_text)
    vector_store.add(
        memory_id,
        completion_text,
        embedding,
        metadata={
            "type": "completion",
            "todo_id": todo_id,
            "title": todo["title"],
        },
    )
    db.set_memory_chroma_id(memory_id, memory_id)

    return {"todo": todo, "memory_id": memory_id}


@app.post("/api/chat")
def chat(payload: ChatRequest):
    message = (payload.message or "").strip()
    if not message:
        raise HTTPException(400, "messageが空です")

    embedding = ai.embed(message)
    ids = vector_store.search(embedding, top_k=5)
    memories = db.get_memories_by_ids(ids) if ids else []
    by_id = {m["id"]: m for m in memories}
    ordered = [by_id[i] for i in ids if i in by_id]

    context_chunks = []
    for m in ordered:
        body = m.get("summary") or m.get("content") or ""
        chunk = f"[{m['type']} / {m['created_at']}]\n{body}"
        context_chunks.append(chunk)

    history_dicts = [t.model_dump() for t in payload.history]
    answer = ai.rag_answer(message, history_dicts, context_chunks)

    sources = [
        {
            "memory_id": m["id"],
            "type": m["type"],
            "summary": m.get("summary") or (m.get("content") or "")[:100],
            "created_at": m["created_at"],
        }
        for m in ordered
    ]
    return {"answer": answer, "sources": sources}


# 静的ファイル
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
def root():
    return FileResponse(str(static_dir / "index.html"))

import json
import os
import re
import time

import google.generativeai as genai

API_KEY = os.getenv("GEMINI_API_KEY", "")
if API_KEY:
    genai.configure(api_key=API_KEY)

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "models/gemini-embedding-001")


def _model(system_instruction=None):
    return genai.GenerativeModel(MODEL_NAME, system_instruction=system_instruction)


def _wait_file_active(file, timeout=60):
    start = time.time()
    while file.state.name == "PROCESSING":
        if time.time() - start > timeout:
            break
        time.sleep(1)
        file = genai.get_file(file.name)
    return file


def transcribe(audio_path, pdf_path=None):
    audio_file = genai.upload_file(audio_path)
    audio_file = _wait_file_active(audio_file)
    parts = [audio_file]
    if pdf_path:
        pdf_file = genai.upload_file(pdf_path)
        pdf_file = _wait_file_active(pdf_file)
        parts.append(pdf_file)
    parts.append(
        "音声を日本語で正確に文字起こししてください。"
        "添付PDFがあれば、その内容も合わせて参照し、関連する補足情報があれば文字起こしの後に追記してください。"
        "出力は文字起こし本文のみで、余計な前置きや見出しは不要です。"
    )
    resp = _model().generate_content(parts)
    return (resp.text or "").strip()


def extract_todos(text):
    prompt = (
        "あなたはタスク管理AIです。\n"
        "以下のテキストからTODOタスクを抽出し、JSONのみで返してください。\n"
        "タスクがなければ空配列を返してください。\n"
        'フォーマット: [{"title":"...", "priority":"high/medium/low", "due_date":"YYYY-MM-DD or null"}]\n'
        f"テキスト: {text}"
    )
    resp = _model().generate_content(prompt)
    raw = (resp.text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE | re.MULTILINE).strip()
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if m:
        raw = m.group(0)
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def summarize(text):
    prompt = (
        "以下のテキストを日本語で簡潔に要約してください。3〜5行程度。前置きなしで要約のみ。\n"
        f"テキスト: {text}"
    )
    resp = _model().generate_content(prompt)
    return (resp.text or "").strip()


def embed(text):
    result = genai.embed_content(model=EMBED_MODEL, content=text)
    return result["embedding"]


def rag_answer(message, history, context_chunks):
    context = "\n---\n".join(context_chunks) if context_chunks else "（参照可能な記録なし）"
    system = (
        "あなたは直人さんの個人アシスタントAIです。\n"
        "以下の「過去のメモ・作業記録」を参照して質問に答えてください。\n"
        "記録にない内容は「記録にありません」と答えてください。"
    )
    convo = ""
    for turn in (history or [])[-10:]:
        role = turn.get("role", "")
        content = turn.get("content", "")
        prefix = "ユーザー" if role == "user" else "アシスタント"
        convo += f"{prefix}: {content}\n"

    user_block = (
        f"[過去のメモ・作業記録]\n{context}\n\n"
        f"[これまでの会話]\n{convo or '（なし）'}\n"
        f"[質問]\n{message}"
    )
    resp = _model(system_instruction=system).generate_content(user_block)
    return (resp.text or "").strip()

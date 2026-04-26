from typing import Optional, List, Literal
from pydantic import BaseModel, Field


class TextInput(BaseModel):
    text: str


class TodoCreate(BaseModel):
    title: str
    description: Optional[str] = None
    priority: Literal["low", "medium", "high"] = "medium"
    due_date: Optional[str] = None


class TodoUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[Literal["low", "medium", "high"]] = None
    due_date: Optional[str] = None
    status: Optional[Literal["pending", "in_progress", "done"]] = None


class TodoComplete(BaseModel):
    completion_note: Optional[str] = None


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatTurn] = Field(default_factory=list)

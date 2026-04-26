import os
from pathlib import Path

import chromadb

DATA_DIR = os.getenv("DATA_DIR", ".")
CHROMA_PATH = Path(DATA_DIR) / "chroma"
COLLECTION_NAME = "memories"

_client_singleton = None


def _client():
    global _client_singleton
    if _client_singleton is None:
        Path(CHROMA_PATH).mkdir(parents=True, exist_ok=True)
        _client_singleton = chromadb.PersistentClient(path=str(CHROMA_PATH))
    return _client_singleton


def get_collection():
    return _client().get_or_create_collection(COLLECTION_NAME)


def add(memory_id, text, embedding, metadata=None):
    coll = get_collection()
    coll.add(
        ids=[memory_id],
        embeddings=[embedding],
        documents=[text],
        metadatas=[metadata or {"_": ""}],
    )


def search(embedding, top_k=5):
    coll = get_collection()
    count = coll.count()
    if count == 0:
        return []
    res = coll.query(
        query_embeddings=[embedding],
        n_results=min(top_k, count),
    )
    ids = res.get("ids", [[]])
    return ids[0] if ids else []

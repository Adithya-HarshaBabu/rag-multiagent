"""FastAPI backend for the chat assistant.

Run from the backend folder:  uvicorn app.main:app --reload --port 8000
"""
import json

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app import config
from app.agents.ingestion import ingest_corpus, load_metadata, save_metadata, summarize
from app.agents.orchestrator import Orchestrator
from app.store import get_client

app = FastAPI(title="Multi-Agent RAG")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
orchestrator = Orchestrator()


class ChatRequest(BaseModel):
    session_id: str
    message: str
    user_tags: list[str] = Field(default_factory=lambda: list(config.DEFAULT_ACCESS_TAGS))
    collection: str = config.ACTIVE_COLLECTION


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/chat")
def chat(req: ChatRequest):
    if req.collection not in config.COLLECTIONS:
        raise HTTPException(400, f"collection must be one of {config.COLLECTIONS}")
    return orchestrator.handle(req.session_id, req.message, req.user_tags, req.collection)


@app.post("/reset/{session_id}")
def reset(session_id: str):
    orchestrator.reset(session_id)
    return {"ok": True}


@app.post("/ingest")
async def ingest(files: list[UploadFile] = File(...), author: str = Form("unknown"),
                 access_tags: str = Form("all_employees")):
    """Upload files -> saved to corpus -> metadata recorded -> ingested into BOTH collections."""
    tags = [t.strip() for t in access_tags.split(",") if t.strip()] or list(config.DEFAULT_ACCESS_TAGS)
    meta, saved = load_metadata(), []
    config.CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    for f in files:
        name = f.filename.replace("\\", "/").split("/")[-1]
        path = config.CORPUS_DIR / name
        if path.suffix.lower() not in config.SUPPORTED_EXTENSIONS:
            raise HTTPException(400, f"Unsupported file type: {name}")
        path.write_bytes(await f.read())
        meta.setdefault(name, {}).update({"author": author, "access_tags": tags})
        saved.append(path)
    save_metadata(meta)
    results = await run_in_threadpool(ingest_corpus, config.COLLECTIONS, saved)
    s = summarize(results)
    s["message"] = f"{s['indexed']} documents indexed ({s['chunks']} chunks across {len(config.COLLECTIONS)} collections)"
    return s


@app.get("/status")
def status():
    client, out = get_client(), {}
    for col in config.COLLECTIONS:
        if not client.collection_exists(col):
            out[col] = {"exists": False, "chunks": 0, "documents": 0}
            continue
        docs, offset = set(), None
        while True:
            pts, offset = client.scroll(col, limit=256, offset=offset, with_payload=["doc_id"], with_vectors=False)
            docs.update(p.payload.get("doc_id") for p in pts)
            if offset is None:
                break
        out[col] = {"exists": True, "chunks": client.count(col, exact=True).count, "documents": len(docs)}
    return {"collections": out, "active_collection": config.ACTIVE_COLLECTION}


@app.get("/logs")
def logs(limit: int = 50):
    path = config.LOG_DIR / "turns.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    return [json.loads(line) for line in lines]

"""Ingestion Agent: load -> clean -> chunk -> embed -> upsert (idempotent)."""
import hashlib
import json
import re
import unicodedata
import uuid
from collections import Counter
from datetime import date
from pathlib import Path

from docx import Document as DocxDocument
from langchain_text_splitters import CharacterTextSplitter, RecursiveCharacterTextSplitter
from pypdf import PdfReader
from qdrant_client import models

from app import config
from app.store import get_client, get_embeddings, with_retry

# ---- Two chunking strategies, one collection each ---------------------------
SPLITTERS = {
    # Strategy A: fixed-size windows, ignores document structure
    "docs_fixed": CharacterTextSplitter(separator=" ", chunk_size=500, chunk_overlap=50),
    # Strategy B: recursive, tries paragraph -> line -> sentence -> word boundaries
    "docs_recursive": RecursiveCharacterTextSplitter(
        chunk_size=800, chunk_overlap=100, separators=["\n\n", "\n", ". ", " ", ""]
    ),
}


# ---- Load --------------------------------------------------------------------
def load_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".docx":
        doc = DocxDocument(str(path))
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:  # keep table content too
            for row in table.rows:
                parts.append(" | ".join(cell.text for cell in row.cells))
        return "\n".join(parts)
    if ext == ".pdf":
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    if ext in {".md", ".txt"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    raise ValueError(f"Unsupported file type: {ext}")


# ---- Clean -------------------------------------------------------------------
PAGE_NUM = re.compile(r"^(page\s*)?\d+(\s*(of|/)\s*\d+)?$", re.I)


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\x00", "")
    lines = [ln.strip() for ln in text.splitlines()]
    counts = Counter(ln for ln in lines if ln)
    out = []
    for ln in lines:
        if PAGE_NUM.match(ln):
            continue  # "Page 2 of 5"
        if ln and counts[ln] >= 3 and len(ln) < 80:
            continue  # repeated header/footer boilerplate
        out.append(re.sub(r"[ \t]+", " ", ln))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


# ---- Metadata ----------------------------------------------------------------
def load_metadata() -> dict:
    if config.METADATA_FILE.exists():
        return json.loads(config.METADATA_FILE.read_text(encoding="utf-8"))
    return {}


def save_metadata(meta: dict) -> None:
    config.METADATA_FILE.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def meta_for(path: Path, all_meta: dict) -> dict:
    m = dict(all_meta.get(path.name, {}))
    m.setdefault("doc_id", re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-"))
    m.setdefault("source", path.name)
    m.setdefault("author", "unknown")
    m.setdefault("date", date.today().isoformat())
    m.setdefault("access_tags", list(config.DEFAULT_ACCESS_TAGS))
    return m


# ---- Embed / store helpers ---------------------------------------------------
def embed_batches(texts: list[str]) -> list[list[float]]:
    emb, out = get_embeddings(), []
    for i in range(0, len(texts), config.EMBED_BATCH):
        out.extend(with_retry(emb.embed_documents, texts[i:i + config.EMBED_BATCH]))
    return out


def ensure_collection(name: str, dim: int) -> None:
    client = get_client()
    if client.collection_exists(name):
        return
    client.create_collection(
        name, vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE)
    )
    for field in ("access_tags", "doc_id", "file_hash"):
        try:
            client.create_payload_index(name, field, models.PayloadSchemaType.KEYWORD)
        except Exception:  # local mode ignores indexes
            pass


def _doc_filter(doc_id: str, file_hash: str | None = None) -> models.Filter:
    must = [models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))]
    if file_hash:
        must.append(models.FieldCondition(key="file_hash", match=models.MatchValue(value=file_hash)))
    return models.Filter(must=must)


def point_id(doc_id: str, idx: int, text: str) -> str:
    """Deterministic ID -> re-running ingestion overwrites instead of duplicating."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc_id}|{idx}|{hashlib.sha256(text.encode()).hexdigest()}"))


# ---- Main entry points -------------------------------------------------------
def ingest_file(path: Path, collection: str, meta: dict) -> dict:
    client = get_client()
    file_hash = hashlib.sha256(path.read_bytes()).hexdigest()

    # Idempotency check 1: identical file already indexed -> skip
    if client.collection_exists(collection):
        existing = client.count(collection, count_filter=_doc_filter(meta["doc_id"], file_hash), exact=True).count
        if existing > 0:
            return {"file": path.name, "collection": collection, "status": "unchanged", "chunks": existing}

    text = clean_text(load_text(path))
    chunks = [c for c in SPLITTERS[collection].split_text(text) if c.strip()]
    if not chunks:
        return {"file": path.name, "collection": collection, "status": "empty", "chunks": 0}

    vectors = embed_batches(chunks)
    ensure_collection(collection, len(vectors[0]))

    # Idempotency check 2: file changed -> remove its old chunks first
    client.delete(collection, points_selector=models.FilterSelector(filter=_doc_filter(meta["doc_id"])))

    points = [
        models.PointStruct(
            id=point_id(meta["doc_id"], i, chunk),
            vector=vec,
            payload={**meta, "text": chunk, "chunk_index": i, "chunk_strategy": collection, "file_hash": file_hash},
        )
        for i, (chunk, vec) in enumerate(zip(chunks, vectors))
    ]
    client.upsert(collection, points=points)

    from app.agents.retrieval import invalidate_keyword_index
    invalidate_keyword_index(collection)
    return {"file": path.name, "collection": collection, "status": "indexed", "chunks": len(points)}


def ingest_corpus(collections: list[str] | None = None, files: list[Path] | None = None) -> list[dict]:
    collections = collections or config.COLLECTIONS
    files = files or sorted(p for p in config.CORPUS_DIR.iterdir() if p.suffix.lower() in config.SUPPORTED_EXTENSIONS)
    all_meta = load_metadata()
    results = []
    for path in files:
        meta = meta_for(path, all_meta)
        for col in collections:
            try:
                results.append(ingest_file(path, col, meta))
            except Exception as e:  # noqa: BLE001
                results.append({"file": path.name, "collection": col, "status": "error", "error": str(e), "chunks": 0})
    return results


def summarize(results: list[dict]) -> dict:
    files_indexed = {r["file"] for r in results if r["status"] == "indexed"}
    return {
        "indexed": len(files_indexed),
        "unchanged": len({r["file"] for r in results if r["status"] == "unchanged"} - files_indexed),
        "errors": [r for r in results if r["status"] == "error"],
        "chunks": sum(r["chunks"] for r in results if r["status"] == "indexed"),
        "details": results,
    }

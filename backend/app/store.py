"""Shared clients: Qdrant, Gemini LLM, Gemini embeddings, cross-encoder + small helpers."""
import json
import re
import time
from functools import lru_cache

from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from qdrant_client import QdrantClient

from app import config


@lru_cache
def get_client() -> QdrantClient:
    if config.QDRANT_URL:
        return QdrantClient(url=config.QDRANT_URL)
    # Local file mode: no server needed. Only ONE process can open the folder at a time.
    return QdrantClient(path=config.QDRANT_PATH)


@lru_cache
def get_embeddings() -> GoogleGenerativeAIEmbeddings:
    return GoogleGenerativeAIEmbeddings(model=config.EMBED_MODEL)


@lru_cache
def get_llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(model=config.LLM_MODEL, temperature=0)


@lru_cache
def get_reranker():
    from sentence_transformers import CrossEncoder
    return CrossEncoder(config.RERANK_MODEL)


def with_retry(fn, *args, attempts=5, **kwargs):
    """Retry on rate limits / transient API errors with exponential backoff."""
    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            if i == attempts - 1:
                raise
            wait = 2 ** i * 2
            print(f"[retry] {type(e).__name__}: {str(e)[:120]} -> sleeping {wait}s")
            time.sleep(wait)


def llm_text(prompt: str) -> str:
    resp = with_retry(get_llm().invoke, prompt)
    content = resp.content
    if isinstance(content, list):  # newer SDKs can return content blocks
        content = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return content.strip()


def parse_json(text: str):
    """Extract the first JSON object/array from an LLM reply (handles ```json fences)."""
    text = re.sub(r"```(?:json)?", "", text).strip()
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        raise ValueError(f"No JSON found in: {text[:200]}")
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]"))
    return json.loads(text[start:end + 1])

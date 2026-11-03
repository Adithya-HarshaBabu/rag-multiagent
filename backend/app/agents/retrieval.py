"""Retrieval Agent: query embedding -> hybrid (dense + BM25) -> RRF -> cross-encoder -> top-k.

Permission filtering is applied INSIDE both searches, so unauthorised chunks never
become candidates (and never reach the LLM).
"""
import re
import time

from qdrant_client import models
from rank_bm25 import BM25Okapi

from app import config
from app.store import get_client, get_embeddings, get_reranker, with_retry

_keyword_cache: dict = {}  # (collection, tags) -> (BM25Okapi, points)


def tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def permission_filter(user_tags: list[str]) -> models.Filter:
    return models.Filter(
        must=[models.FieldCondition(key="access_tags", match=models.MatchAny(any=user_tags))]
    )


def invalidate_keyword_index(collection: str) -> None:
    for key in [k for k in _keyword_cache if k[0] == collection]:
        del _keyword_cache[key]


def _scroll_all(collection: str, flt: models.Filter):
    client, points, offset = get_client(), [], None
    while True:
        batch, offset = client.scroll(
            collection, scroll_filter=flt, limit=256, offset=offset, with_payload=True, with_vectors=False
        )
        points.extend(batch)
        if offset is None:
            return points


def _keyword_index(collection: str, user_tags: list[str]):
    key = (collection, tuple(sorted(user_tags)))
    if key not in _keyword_cache:
        pts = _scroll_all(collection, permission_filter(user_tags))
        bm25 = BM25Okapi([tokenize(p.payload["text"]) for p in pts]) if pts else None
        _keyword_cache[key] = (bm25, pts)
    return _keyword_cache[key]


def _to_chunk(point, score: float) -> dict:
    p = point.payload
    return {
        "id": str(point.id),
        "text": p["text"],
        "source": p.get("source"),
        "doc_id": p.get("doc_id"),
        "author": p.get("author"),
        "date": p.get("date"),
        "chunk_index": p.get("chunk_index"),
        "score": float(score),
    }


def retrieve(query: str, collection: str, user_tags: list[str], k: int = config.TOP_K,
             n: int = config.CANDIDATES, rerank: bool = True, mode: str = "hybrid") -> dict:
    """mode: 'hybrid' | 'dense' | 'keyword' (useful for evaluation comparisons)."""
    client = get_client()
    timings = {}
    if not client.collection_exists(collection):
        return {"chunks": [], "timings": timings}
    flt = permission_filter(user_tags)

    # 1) Semantic search (same embedding model as ingestion)
    dense = []
    if mode in ("hybrid", "dense"):
        t = time.perf_counter()
        qvec = with_retry(get_embeddings().embed_query, query)
        dense = client.query_points(collection, query=qvec, query_filter=flt, limit=n, with_payload=True).points
        timings["dense_ms"] = round((time.perf_counter() - t) * 1000, 1)

    # 2) Keyword search (BM25 over permitted chunks)
    keyword = []
    if mode in ("hybrid", "keyword"):
        t = time.perf_counter()
        bm25, pts = _keyword_index(collection, user_tags)
        if bm25:
            scores = bm25.get_scores(tokenize(query))
            order = sorted(range(len(pts)), key=lambda i: -scores[i])[:n]
            keyword = [pts[i] for i in order if scores[i] > 0]
        timings["keyword_ms"] = round((time.perf_counter() - t) * 1000, 1)

    # 3) Merge with Reciprocal Rank Fusion
    fused: dict = {}
    for ranked in (dense, keyword):
        for rank, p in enumerate(ranked):
            entry = fused.setdefault(str(p.id), [0.0, p])
            entry[0] += 1.0 / (60 + rank + 1)
    candidates = sorted(fused.values(), key=lambda x: -x[0])[:n]
    if not candidates:
        return {"chunks": [], "timings": timings}

    # 4) Cross-encoder re-rank
    if rerank:
        t = time.perf_counter()
        pts = [p for _, p in candidates]
        ce_scores = get_reranker().predict([(query, p.payload["text"]) for p in pts])
        ranked = sorted(zip(ce_scores, pts), key=lambda x: -x[0])[:k]
        timings["rerank_ms"] = round((time.perf_counter() - t) * 1000, 1)
        chunks = [_to_chunk(p, s) for s, p in ranked]
    else:
        # No re-ranker: keep RRF order; score set high so the no-context gate doesn't fire
        chunks = [_to_chunk(p, 99.0) for _, p in candidates[:k]]

    return {"chunks": chunks, "timings": timings}

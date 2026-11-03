"""Ingest everything in data/corpus into both collections.

Run from the backend folder:  python -m scripts.ingest_all
Re-running is safe: unchanged files are skipped, changed files are replaced.
"""
from app import config
from app.agents.ingestion import ingest_corpus, summarize

if __name__ == "__main__":
    results = ingest_corpus(config.COLLECTIONS)
    print(f"{'file':35} {'collection':16} {'status':10} chunks")
    for r in results:
        print(f"{r['file']:35} {r['collection']:16} {r['status']:10} {r['chunks']}  {r.get('error', '')}")
    s = summarize(results)
    print(f"\nIndexed {s['indexed']} docs ({s['chunks']} chunks), unchanged {s['unchanged']}, errors {len(s['errors'])}")

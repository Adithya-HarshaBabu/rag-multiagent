# Multi-Agent RAG Framework — Document Ingestion & Retrieval

Four cooperating agents: **Orchestrator → Ingestion / Retrieval → Synthesis**. They are backed by
Qdrant, Gemini and a cross-encoder re-ranker, with a React chat UI.

```
backend/
  app/config.py              settings (.env)
  app/store.py               Qdrant / Gemini / cross-encoder clients + helpers
  app/agents/ingestion.py    load → clean → chunk (2 strategies) → embed → upsert (idempotent)
  app/agents/retrieval.py    dense + BM25 → RRF → cross-encoder → permission-filtered top-k
  app/agents/synthesis.py    cited answer + per-sentence hallucination check + no-context handling
  app/agents/orchestrator.py intent routing, follow-up rewriting, session state, turn logging
  app/main.py                FastAPI: /chat /ingest /status /logs /reset
  scripts/make_sample_corpus.py   generates 9 sample docs (DOCX/PDF/MD) + metadata.json
  scripts/ingest_all.py      ingests the corpus into both collections
  evaluation/evaluate.py     recall@k, MRR, accuracy, faithfulness, refusals, leaks, latency
  data/eval/questions.json   26 test questions (answerable, permission, unanswerable)
frontend/                    React (Vite) chat UI
docs/                        architecture diagram (Mermaid) + evaluation report template
```

## 1. Backend setup (Heropa VM)
```bash
cd backend
python -m venv venv
venv\Scripts\activate            # Windows   (Linux/Mac: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env           # Linux/Mac: cp .env.example .env  -> then put your GOOGLE_API_KEY in it
```
By default, Qdrant runs in **local file mode** (`backend/qdrant_data/`), so you don't need Docker.
If Docker is available, you can run a server instead and set `QDRANT_URL=http://localhost:6333` in `.env`:
```bash
docker run -p 6333:6333 -v qdrant_storage:/qdrant/storage qdrant/qdrant
```
> Local file mode allows only **one process** at a time. Stop the API server before running
> `ingest_all` or `evaluate`, or use the Docker server, which allows several processes.

## 2. Create the corpus and ingest it
```bash
python -m scripts.make_sample_corpus   # or put your own files + metadata.json in data/corpus/
python -m scripts.ingest_all           # run it twice: the second run should say "unchanged"
```
The first run downloads the cross-encoder model from Hugging Face (~90 MB). If Heropa blocks
huggingface.co, download the model elsewhere, copy the folder in, and set `RERANK_MODEL=<folder path>`.

## 3. Run the API
```bash
uvicorn app.main:app --reload --port 8000
```
Open http://localhost:8000/docs to try the endpoints.

## 4. Run the UI
```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```
Things to try in the demo:
- **Grounded answer with citations:** "How many days of leave do I get?" → click the [1] chip.
- **Follow-up (conversation state):** "what about contractors?"
- **Clarification:** "tell me about the policy"
- **No context:** "Who is the CEO?"
- **Permissions:** as *Employee*, ask "What is the Engineer II salary band?" (it refuses); switch to *HR Admin* and ask again (it answers).
- **Ingestion:** upload a file, or type "re-index the documents".

## 5. Evaluate (stop the API first if you use local file mode)
```bash
python -m evaluation.evaluate --retrieval-only      # fast: recall / MRR / latency only
python -m evaluation.evaluate                       # full: also accuracy, faithfulness, refusals
python -m evaluation.evaluate --configs docs_fixed:hybrid:rerank docs_recursive:hybrid:rerank docs_recursive:hybrid:norerank docs_recursive:dense:rerank
```
Results are written to `evaluation/results/`. Paste the summary table into `docs/eval_report_template.md`.

## 6. Architecture diagram
Paste `docs/architecture.mmd` into https://mermaid.live and export it as PNG, or redraw it in draw.io.

## Mapping to the submission checklist
| Deliverable | Where |
|---|---|
| Ingestion pipeline | `agents/ingestion.py`, `scripts/ingest_all.py` |
| Vector DB + metadata | Qdrant collections `docs_fixed`, `docs_recursive` (payload: source, author, date, access_tags, chunk_index) |
| Hybrid search + re-rank, recall | `agents/retrieval.py`, `evaluation/evaluate.py` |
| Orchestrator, multi-turn | `agents/orchestrator.py` |
| Grounded answers + hallucination check | `agents/synthesis.py` |
| React chat with citations | `frontend/src/App.jsx` |
| Evaluation report | `evaluation/results/*` + `docs/eval_report_template.md` |
| Architecture diagram | `docs/architecture.mmd` |

## Troubleshooting
- **429 / quota errors:** the free Gemini tier is rate-limited. The code retries with backoff; you can also raise `--sleep` in the evaluation.
- **"Storage folder ... is already accessed by another instance":** another process has Qdrant local mode open. Stop it.
- **Everything returns "no context":** lower `MIN_RERANK_SCORE` in `.env` (for example to `-3`).
- **Changed the embedding model?** Delete `qdrant_data/` and re-ingest, because the vector size changes.

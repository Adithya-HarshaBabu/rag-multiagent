# Evaluation Report — Chunking Strategy Comparison

**Author:** <your name>  **Date:** <date>

## 1. Setup
- Corpus: <N> documents (<x> DOCX, <y> PDF, <z> MD), domain: <domain>
- Test set: <N> questions (<a> answerable, <b> permission tests, <c> unanswerable)
- Embeddings: gemini-embedding-001 · LLM: gemini-2.5-flash · Re-ranker: cross-encoder/ms-marco-MiniLM-L-6-v2
- Retrieval: hybrid (dense + BM25, RRF k=60), 20 candidates → re-rank → top-5

| Config | Chunker | Size / overlap | # chunks |
|---|---|---|---|
| A — docs_fixed | CharacterTextSplitter | 500 / 50 | <n> |
| B — docs_recursive | RecursiveCharacterTextSplitter | 800 / 100 | <n> |

## 2. Results
_Paste the table from `evaluation/results/summary_*.md`._

| Metric | A: fixed | B: recursive | B: recursive, no re-rank |
|---|---|---|---|
| Hit@5 | | | |
| Recall@5 | | | |
| MRR | | | |
| Answer accuracy | | | |
| Faithfulness | | | |
| Refusal accuracy (unanswerable) | | | |
| Permission leaks | | | |
| Retrieval p50 / p95 (ms) | | | |
| End-to-end p50 / p95 (ms) | | | |

## 3. Analysis
- **Retrieval accuracy:** which strategy ranked the right source higher, and why (e.g. fixed chunks split sentences mid-way).
- **Faithfulness:** how often the hallucination check removed claims; examples.
- **Latency:** where time goes (embedding call, re-ranker, LLM ×2).
- **Effect of re-ranking:** MRR with vs without the cross-encoder.

## 4. Failure examples
| Question | Config | What went wrong | Likely fix |
|---|---|---|---|
| | | | |

## 5. Conclusion
Recommended configuration: <A/B>, because <reason>. Next improvements: <e.g. semantic chunking, query expansion, metadata boosting>.

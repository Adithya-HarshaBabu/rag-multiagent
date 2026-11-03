"""Evaluate retrieval + answers for each configuration and write a comparison report.

Run from the backend folder (stop the API server first if using Qdrant local file mode):
    python -m evaluation.evaluate                                  # both collections, hybrid + rerank
    python -m evaluation.evaluate --configs docs_fixed:hybrid:rerank docs_recursive:hybrid:rerank docs_recursive:hybrid:norerank
    python -m evaluation.evaluate --retrieval-only                 # skip LLM answers (fast, cheap)

Config format:  <collection>:<hybrid|dense|keyword>:<rerank|norerank>
"""
import argparse
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

from app import config
from app.agents.retrieval import retrieve
from app.agents.synthesis import NO_CONTEXT_ANSWER, synthesize
from app.store import llm_text, parse_json

OUT_DIR = Path(__file__).resolve().parent / "results"

JUDGE_PROMPT = """Compare the ASSISTANT ANSWER to the EXPECTED ANSWER for the question.
Return ONLY JSON: {{"correct": true/false}}. "correct" means it contains the key facts of the expected answer
and nothing contradicting it.
Question: {q}
EXPECTED ANSWER: {expected}
ASSISTANT ANSWER: {answer}"""


def pct(values, p):
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(round(p / 100 * (len(values) - 1))))]


def mean(values):
    values = [v for v in values if v is not None]
    return statistics.mean(values) if values else None


def evaluate_config(cfg: str, questions: list, k: int, retrieval_only: bool, sleep: float) -> dict:
    collection, mode, rr = cfg.split(":")
    rerank = rr == "rerank"
    rows = []
    for q in questions:
        t0 = time.perf_counter()
        r = retrieve(q["question"], collection, q["user_tags"], k=k, rerank=rerank, mode=mode)
        retrieval_ms = (time.perf_counter() - t0) * 1000
        sources = [c["source"] for c in r["chunks"]]
        expected = q.get("expected_sources", [])
        row = {"id": q["id"], "question": q["question"], "retrieved_sources": sources,
               "retrieval_ms": round(retrieval_ms, 1)}

        if expected:  # answerable question -> retrieval metrics
            row["hit@k"] = int(any(s in sources for s in expected))
            row["recall@k"] = sum(1 for s in expected if s in sources) / len(expected)
            first = next((i for i, s in enumerate(sources) if s in expected), None)
            row["mrr"] = 1 / (first + 1) if first is not None else 0.0
        if q.get("forbidden_sources"):  # permission test
            row["leak"] = int(any(s in sources for s in q["forbidden_sources"]))

        if not retrieval_only:
            t1 = time.perf_counter()
            ans = synthesize(q["question"], r["chunks"])
            row["total_ms"] = round(retrieval_ms + (time.perf_counter() - t1) * 1000, 1)
            row["answer"] = ans["answer"]
            row["faithfulness"] = ans["faithfulness"]
            is_no_ctx = ans["answer"] == NO_CONTEXT_ANSWER
            if q["expected_answer"] == "NO_CONTEXT":
                row["correct"] = int(is_no_ctx)  # should refuse
            elif is_no_ctx:
                row["correct"] = 0
            else:
                try:
                    row["correct"] = int(bool(parse_json(llm_text(JUDGE_PROMPT.format(
                        q=q["question"], expected=q["expected_answer"], answer=ans["answer"])))["correct"]))
                except Exception:  # noqa: BLE001
                    row["correct"] = None
            time.sleep(sleep)  # be gentle with free-tier rate limits
        rows.append(row)
        print(f"  {cfg} {q['id']}: hit={row.get('hit@k', '-')} correct={row.get('correct', '-')}")

    ans_rows = [r for r in rows if "hit@k" in r]
    summary = {
        "config": cfg,
        "n_questions": len(rows),
        f"hit@{k}": mean([r["hit@k"] for r in ans_rows]),
        f"recall@{k}": mean([r["recall@k"] for r in ans_rows]),
        "mrr": mean([r["mrr"] for r in ans_rows]),
        "permission_leaks": sum(r.get("leak", 0) for r in rows),
        "retrieval_p50_ms": pct([r["retrieval_ms"] for r in rows], 50),
        "retrieval_p95_ms": pct([r["retrieval_ms"] for r in rows], 95),
    }
    if not retrieval_only:
        summary.update({
            "answer_accuracy": mean([r.get("correct") for r in rows]),
            "faithfulness": mean([r.get("faithfulness") for r in rows]),
            "refusal_accuracy": mean([r["correct"] for r, q in zip(rows, questions) if q["expected_answer"] == "NO_CONTEXT"]),
            "total_p50_ms": pct([r["total_ms"] for r in rows], 50),
            "total_p95_ms": pct([r["total_ms"] for r in rows], 95),
        })
    return {"summary": summary, "rows": rows}


def fmt(v):
    if v is None:
        return "-"
    return f"{v:.3f}" if isinstance(v, float) else str(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", nargs="+",
                    default=["docs_fixed:hybrid:rerank", "docs_recursive:hybrid:rerank"])
    ap.add_argument("--k", type=int, default=config.TOP_K)
    ap.add_argument("--retrieval-only", action="store_true")
    ap.add_argument("--sleep", type=float, default=1.0)
    args = ap.parse_args()

    questions = json.loads(config.QUESTIONS_FILE.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results = [evaluate_config(c, questions, args.k, args.retrieval_only, args.sleep) for c in args.configs]

    (OUT_DIR / f"results_{stamp}.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    keys = list(results[0]["summary"].keys())
    lines = [f"# Evaluation results ({stamp})", "",
             "| metric | " + " | ".join(r["summary"]["config"] for r in results) + " |",
             "|---|" + "---|" * len(results)]
    for key in keys[1:]:
        lines.append(f"| {key} | " + " | ".join(fmt(r["summary"].get(key)) for r in results) + " |")
    lines += ["", "## Misses (answerable questions where no expected source was retrieved)"]
    for r in results:
        misses = [row["id"] for row in r["rows"] if row.get("hit@k") == 0]
        lines.append(f"- {r['summary']['config']}: {', '.join(misses) or 'none'}")
    report = "\n".join(lines)
    (OUT_DIR / f"summary_{stamp}.md").write_text(report, encoding="utf-8")
    print("\n" + report)


if __name__ == "__main__":
    main()

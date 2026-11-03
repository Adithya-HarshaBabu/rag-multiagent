"""Synthesis Agent: grounded answer with inline citations + hallucination check."""
import re

from app import config
from app.store import llm_text, parse_json

NO_CONTEXT_ANSWER = (
    "I couldn't find information about that in the documents you have access to. "
    "Try rephrasing, or upload a document that covers it."
)

ANSWER_PROMPT = """You are a careful assistant answering questions from company documents.
Use ONLY the numbered context passages below. Do not use outside knowledge.
- Cite every factual sentence with the passage number(s) in square brackets, e.g. [1] or [2][3].
- Be concise (at most 6 sentences).
- If the passages do not contain the answer, reply with exactly: NO_ANSWER

Context:
{context}

Question: {question}
Answer:"""

VERIFY_PROMPT = """You are a strict fact-checker. Split the ANSWER into its sentences.
For each sentence decide whether it is fully supported by the CONTEXT (not by general knowledge).
Return ONLY a JSON list like:
[{{"sentence": "<exact sentence from the answer>", "supported": true}}]

CONTEXT:
{context}

ANSWER:
{answer}"""


def format_context(chunks: list[dict]) -> str:
    return "\n\n".join(f"[{i + 1}] (source: {c['source']}) {c['text']}" for i, c in enumerate(chunks))


def no_context(reason: str) -> dict:
    return {"answer": NO_CONTEXT_ANSWER, "citations": [], "grounded": False,
            "faithfulness": None, "unsupported_claims": [], "no_context_reason": reason}


def synthesize(question: str, chunks: list[dict], min_score: float = config.MIN_RERANK_SCORE,
               check: bool = True) -> dict:
    # Gate 1: nothing relevant retrieved
    if not chunks:
        return no_context("no_chunks")
    if chunks[0]["score"] < min_score:
        return no_context("low_relevance")

    context = format_context(chunks)
    answer = llm_text(ANSWER_PROMPT.format(context=context, question=question))

    # Gate 2: model says the context doesn't answer it
    if "NO_ANSWER" in answer:
        return no_context("model_no_answer")

    # Hallucination check: every claim must trace back to a retrieved chunk
    verdicts, unsupported = [], []
    if check:
        try:
            verdicts = parse_json(llm_text(VERIFY_PROMPT.format(context=context, answer=answer)))
            unsupported = [v["sentence"] for v in verdicts if not v.get("supported")]
        except Exception:  # noqa: BLE001  - if the checker fails, keep answer but mark unknown
            verdicts = []
        for sentence in unsupported:  # suppress unsupported claims
            answer = answer.replace(sentence, "").strip()
        if verdicts and not answer.strip(" .\n"):
            return no_context("all_claims_unsupported")
        if unsupported:
            answer += "\n\n(Some statements were removed because they could not be verified against the sources.)"

    faithfulness = (sum(1 for v in verdicts if v.get("supported")) / len(verdicts)) if verdicts else None
    cited = {int(n) for n in re.findall(r"\[(\d+)\]", answer)}
    citations = [
        {"n": i + 1, "source": c["source"], "doc_id": c["doc_id"], "chunk_index": c["chunk_index"],
         "score": round(c["score"], 3), "snippet": c["text"][:400]}
        for i, c in enumerate(chunks) if (i + 1) in cited
    ]
    return {"answer": answer, "citations": citations, "grounded": True,
            "faithfulness": faithfulness, "unsupported_claims": unsupported}

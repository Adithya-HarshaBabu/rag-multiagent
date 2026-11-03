"""Orchestrator Agent: intent classification, query rewriting, routing, conversation state, logging."""
import json
import time
from collections import defaultdict
from datetime import datetime, timezone

from app import config
from app.agents.ingestion import ingest_corpus, summarize
from app.agents.retrieval import retrieve
from app.agents.synthesis import synthesize
from app.store import llm_text, parse_json

ROUTER_PROMPT = """You are the orchestrator of a company-document assistant.
Decide what to do with the user's latest message. Return ONLY JSON:
{{"intent": "ingest" | "question" | "clarify",
  "standalone_query": "<question rewritten to be self-contained, or empty>",
  "clarifying_question": "<one short question, or empty>"}}

Rules:
- "ingest": the user asks to add, index, re-index, refresh or load documents.
- "question": the user asks something that could be answered from documents.
  Rewrite follow-ups into a standalone query using the history
  (e.g. history about leave + "what about contractors?" -> "How much paid leave do contractors get?").
- "clarify": the message is too vague or ambiguous to search (e.g. "tell me about the policy"
  when several policies could match, or "what about it?" with no history), or it's just a greeting.
  Ask ONE short clarifying question. Do not guess.

Conversation history:
{history}

User: {message}"""


class Orchestrator:
    def __init__(self):
        self.sessions = defaultdict(lambda: {"history": []})
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)

    def route(self, history: list, message: str) -> dict:
        hist = "\n".join(f"{role}: {text}" for role, text in history[-8:]) or "(no history)"
        try:
            r = parse_json(llm_text(ROUTER_PROMPT.format(history=hist, message=message)))
            if r.get("intent") not in {"ingest", "question", "clarify"}:
                r["intent"] = "question"
            return r
        except Exception:  # noqa: BLE001 - fall back to treating it as a question
            return {"intent": "question", "standalone_query": message, "clarifying_question": ""}

    def handle(self, session_id: str, message: str, user_tags: list[str], collection: str) -> dict:
        t0 = time.perf_counter()
        session = self.sessions[session_id]
        route = self.route(session["history"], message)
        intent = route["intent"]
        retrieved, timings = [], {}

        if intent == "clarify":
            result = {"answer": route.get("clarifying_question") or "Could you tell me a bit more about what you're looking for?",
                      "citations": [], "grounded": False}
        elif intent == "ingest":
            s = summarize(ingest_corpus(config.COLLECTIONS))  # both collections stay in sync
            result = {"answer": f"Ingestion finished: {s['indexed']} documents indexed ({s['chunks']} chunks), "
                                f"{s['unchanged']} unchanged, {len(s['errors'])} errors.",
                      "citations": [], "grounded": False, "ingestion": {k: v for k, v in s.items() if k != "details"}}
        else:
            query = route.get("standalone_query") or message
            r = retrieve(query, collection, user_tags)
            retrieved, timings = r["chunks"], r["timings"]
            t = time.perf_counter()
            result = synthesize(query, retrieved)
            timings["synthesis_ms"] = round((time.perf_counter() - t) * 1000, 1)

        result.update({
            "intent": intent,
            "standalone_query": route.get("standalone_query", ""),
            "collection": collection,
            "timings": timings,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        })
        session["history"] += [("user", message), ("assistant", result["answer"][:600])]
        self.log_turn(session_id, message, user_tags, retrieved, result)
        return result

    def reset(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)

    @staticmethod
    def log_turn(session_id, message, user_tags, retrieved, result):
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "query": message,
            "standalone_query": result.get("standalone_query"),
            "intent": result.get("intent"),
            "user_tags": user_tags,
            "collection": result.get("collection"),
            "retrieved": [{"id": c["id"], "source": c["source"], "score": c["score"]} for c in retrieved],
            "answer": result.get("answer"),
            "faithfulness": result.get("faithfulness"),
            "latency_ms": result.get("latency_ms"),
        }
        with open(config.LOG_DIR / "turns.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

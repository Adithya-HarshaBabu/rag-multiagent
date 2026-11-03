import { useEffect, useRef, useState } from "react";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

// Demo roles -> access tags (used by the Retrieval Agent's permission filter)
const ROLES = {
  Employee: ["all_employees"],
  Engineer: ["all_employees", "engineering"],
  "HR Admin": ["all_employees", "hr_only"],
};

const newSessionId = () =>
  (crypto.randomUUID ? crypto.randomUUID() : String(Date.now() + Math.random()));

function AnswerText({ text, onCite }) {
  // Turn "[2]" markers into clickable citation chips
  const parts = text.split(/(\[\d+\])/g);
  return (
    <p className="answer-text">
      {parts.map((part, i) => {
        const m = part.match(/^\[(\d+)\]$/);
        return m ? (
          <button key={i} className="cite-chip" onClick={() => onCite(Number(m[1]))}>
            {m[1]}
          </button>
        ) : (
          <span key={i}>{part}</span>
        );
      })}
    </p>
  );
}

function AssistantMessage({ msg }) {
  const [open, setOpen] = useState(null);
  const active = msg.citations?.find((c) => c.n === open);
  return (
    <div className="msg assistant">
      <AnswerText text={msg.content} onCite={(n) => setOpen(open === n ? null : n)} />
      {msg.citations?.length > 0 && (
        <div className="sources">
          <span className="sources-label">Sources:</span>
          {msg.citations.map((c) => (
            <button key={c.n} className={`source ${open === c.n ? "on" : ""}`}
                    onClick={() => setOpen(open === c.n ? null : c.n)}>
              [{c.n}] {c.source} · chunk {c.chunk_index}
            </button>
          ))}
        </div>
      )}
      {active && (
        <blockquote className="snippet">
          <strong>{active.source}</strong> (chunk {active.chunk_index}, score {active.score})
          <br />
          {active.snippet}…
        </blockquote>
      )}
      <div className="meta">
        {msg.intent && <span>intent: {msg.intent}</span>}
        {msg.faithfulness != null && <span>faithfulness: {(msg.faithfulness * 100).toFixed(0)}%</span>}
        {msg.latency_ms != null && <span>{Math.round(msg.latency_ms)} ms</span>}
        {msg.unsupported_claims?.length > 0 && (
          <span className="warn">{msg.unsupported_claims.length} unverified claim(s) removed</span>
        )}
      </div>
    </div>
  );
}

export default function App() {
  const [sessionId, setSessionId] = useState(newSessionId);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [role, setRole] = useState("Employee");
  const [collection, setCollection] = useState("docs_recursive");
  const [status, setStatus] = useState(null);
  const [banner, setBanner] = useState("");
  const [files, setFiles] = useState([]);
  const [uploadTags, setUploadTags] = useState("all_employees");
  const endRef = useRef(null);

  const loadStatus = () =>
    fetch(`${API}/status`).then((r) => r.json()).then(setStatus).catch(() => setStatus(null));

  useEffect(() => { loadStatus(); }, []);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, loading]);

  async function send(e) {
    e.preventDefault();
    const text = input.trim();
    if (!text || loading) return;
    setMessages((m) => [...m, { role: "user", content: text }]);
    setInput("");
    setLoading(true);
    try {
      const res = await fetch(`${API}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, message: text, user_tags: ROLES[role], collection }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setMessages((m) => [...m, { role: "assistant", content: data.answer, ...data }]);
      if (data.intent === "ingest") { setBanner(data.answer); loadStatus(); }
    } catch (err) {
      setMessages((m) => [...m, { role: "assistant", content: `Error: ${err.message}` }]);
    } finally {
      setLoading(false);
    }
  }

  async function upload(e) {
    e.preventDefault();
    if (!files.length) return;
    const form = new FormData();
    [...files].forEach((f) => form.append("files", f));
    form.append("access_tags", uploadTags);
    setBanner("Indexing…");
    try {
      const res = await fetch(`${API}/ingest`, { method: "POST", body: form });
      const data = await res.json();
      setBanner(res.ok ? `✅ ${data.message}` : `❌ ${data.detail}`);
      loadStatus();
    } catch (err) {
      setBanner(`❌ ${err.message}`);
    }
  }

  function newChat() {
    fetch(`${API}/reset/${sessionId}`, { method: "POST" }).catch(() => {});
    setSessionId(newSessionId());
    setMessages([]);
  }

  const col = status?.collections?.[collection];

  return (
    <div className="layout">
      <aside className="sidebar">
        <h2>Knowledge Assistant</h2>

        <label>Signed in as
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            {Object.keys(ROLES).map((r) => <option key={r}>{r}</option>)}
          </select>
        </label>
        <small>Access tags: {ROLES[role].join(", ")}</small>

        <label>Chunking strategy
          <select value={collection} onChange={(e) => setCollection(e.target.value)}>
            <option value="docs_recursive">Recursive (docs_recursive)</option>
            <option value="docs_fixed">Fixed-size (docs_fixed)</option>
          </select>
        </label>

        <div className="status">
          {col ? (col.exists ? `📚 ${col.documents} documents · ${col.chunks} chunks indexed`
                             : "No documents indexed yet")
               : "Backend not reachable"}
        </div>

        <form onSubmit={upload} className="upload">
          <strong>Add documents</strong>
          <input type="file" multiple accept=".pdf,.docx,.md,.txt" onChange={(e) => setFiles(e.target.files)} />
          <input value={uploadTags} onChange={(e) => setUploadTags(e.target.value)} placeholder="access tags, comma separated" />
          <button type="submit">Upload & index</button>
        </form>
        {banner && <div className="banner">{banner}</div>}

        <button className="secondary" onClick={newChat}>New conversation</button>
      </aside>

      <main className="chat">
        <div className="messages">
          {messages.length === 0 && (
            <div className="empty">Ask a question about your documents, e.g. “How many days of leave do I get?”</div>
          )}
          {messages.map((m, i) =>
            m.role === "user"
              ? <div key={i} className="msg user">{m.content}</div>
              : <AssistantMessage key={i} msg={m} />
          )}
          {loading && <div className="msg assistant typing">Thinking…</div>}
          <div ref={endRef} />
        </div>
        <form className="composer" onSubmit={send}>
          <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Type your question…" autoFocus />
          <button type="submit" disabled={loading}>Send</button>
        </form>
      </main>
    </div>
  );
}

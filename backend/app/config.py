import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

CORPUS_DIR = BASE_DIR / "data" / "corpus"
METADATA_FILE = CORPUS_DIR / "metadata.json"
QUESTIONS_FILE = BASE_DIR / "data" / "eval" / "questions.json"
LOG_DIR = BASE_DIR / "logs"

QDRANT_URL = os.getenv("QDRANT_URL", "").strip()
QDRANT_PATH = os.getenv("QDRANT_PATH", str(BASE_DIR / "qdrant_data"))

LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")
EMBED_MODEL = os.getenv("EMBED_MODEL", "models/gemini-embedding-001")
RERANK_MODEL = os.getenv("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")

# Two chunking strategies -> two separate collections (fair comparison)
COLLECTIONS = ["docs_fixed", "docs_recursive"]
ACTIVE_COLLECTION = os.getenv("ACTIVE_COLLECTION", "docs_recursive")

TOP_K = int(os.getenv("TOP_K", "5"))
CANDIDATES = int(os.getenv("CANDIDATES", "20"))
MIN_RERANK_SCORE = float(os.getenv("MIN_RERANK_SCORE", "-1.0"))
EMBED_BATCH = int(os.getenv("EMBED_BATCH", "50"))

DEFAULT_ACCESS_TAGS = ["all_employees"]
SUPPORTED_EXTENSIONS = {".docx", ".pdf", ".md", ".txt"}

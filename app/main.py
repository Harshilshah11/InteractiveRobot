"""FastAPI app: static UI + /api/ask + /api/reindex (+ optional /api/stt)."""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import embedder, ingest, store
from .answerer import respond
from .config import (
    CLARIFY_THRESHOLD,
    CLOSING,
    CLOSING_DELAY_MS,
    CONTACT_EMAIL,
    CONTACT_PHONE,
    CONTACT_WEB,
    FALLBACK,
    THRESHOLD,
    WEB_DIR,
    WHISPER_ENABLED,
    WHISPER_MODEL,
)
from .products import DEFAULT_FOLLOWUPS, PRODUCTS
from .retriever import Retriever

_retriever: Retriever | None = None
_lock = threading.Lock()
_whisper: dict = {}
_whisper_lock = threading.Lock()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Rebuild whenever data/ is newer than the index, so editing a knowledge
    # file and restarting is all it takes — there is no stale-index trap.
    if ingest.is_stale():
        ingest.build()
    get_retriever()
    # Load the ONNX model now so the first question is not the one that waits.
    embedder.embed_query("warm up")
    # Same for speech-to-text, but off the startup path: the model takes a
    # while to load and the page is usable by typing in the meantime.
    if WHISPER_ENABLED:
        threading.Thread(target=_whisper_model, daemon=True).start()
    yield


def _whisper_model():
    with _whisper_lock:
        if "model" not in _whisper:
            from faster_whisper import WhisperModel

            _whisper["model"] = WhisperModel(
                WHISPER_MODEL, device="cpu", compute_type="int8"
            )
    return _whisper["model"]


app = FastAPI(
    title="InteractiveRobot",
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
)


def get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        with _lock:
            if _retriever is None:
                conn = store.connect()
                chunks = store.load_all(conn)
                conn.close()
                _retriever = Retriever(chunks)
    return _retriever


class Ask(BaseModel):
    question: str


@app.post("/api/ask")
def ask(body: Ask):
    question = (body.question or "").strip()
    if not question:
        return {
            "answer": FALLBACK,
            "answered": False,
            "mode": "refer",
            "confidence": 0.0,
            "followups": list(DEFAULT_FOLLOWUPS),
            "sources": [],
        }

    retriever = get_retriever()
    if not retriever.chunks:
        return JSONResponse(
            status_code=503,
            content={
                "answer": "Knowledge base is empty. Add files to data/ and reindex.",
                "answered": False,
                "mode": "refer",
                "confidence": 0.0,
                "followups": [],
                "sources": [],
            },
        )

    # The retriever is passed through so a product answer can read that
    # product's other sections by name, not just the one that ranked first.
    result = respond(question, retriever)
    result["threshold"] = THRESHOLD
    return result


@app.post("/api/reindex")
def reindex():
    global _retriever
    result = ingest.build()
    with _lock:
        _retriever = None
    get_retriever()
    return result


@app.get("/api/products")
def products_list():
    """The product cards in the UI.

    Served rather than hardcoded in the page so the range is defined once, in
    `app/products.py`. Deliberately carries no figures — a card that quoted a
    payload could drift out of step with data/company.md, and the answer behind
    the card is where the numbers belong.
    """
    return {
        "products": [
            {
                "key": key,
                "name": product["name"],
                "kind": product["kind"],
                "ask": f"Tell me about {product['name']}",
            }
            for key, product in PRODUCTS.items()
        ]
    }


@app.get("/api/health")
def health():
    retriever = get_retriever()
    conn = store.connect()
    indexed_with = store.get_meta(conn, "embedder", "unknown")
    conn.close()
    return {
        "chunks": len(retriever.chunks),
        "vectors": retriever.has_vectors,
        "embedder": indexed_with,  # what the index was built with
        "runtime": embedder.status(),  # what this process has loaded
        "threshold": THRESHOLD,
        "clarify_threshold": CLARIFY_THRESHOLD,
        "offline_stt": WHISPER_ENABLED,
        # The page speaks this when the room goes quiet after an answer. Served
        # rather than hardcoded so every line the robot says is configurable in
        # one place, by environment variable, like all the others.
        "closing": CLOSING,
        "closing_delay_ms": CLOSING_DELAY_MS,
        # Shown on the page's contact card, from the same settings the spoken
        # referral uses, so the two can never disagree.
        "contact": {"phone": CONTACT_PHONE, "email": CONTACT_EMAIL, "web": CONTACT_WEB},
    }


@app.post("/api/stt")
async def stt(audio: UploadFile):
    """Fully offline speech-to-text. Enable with ROBOT_WHISPER=on."""
    if not WHISPER_ENABLED:
        return JSONResponse(
            status_code=501,
            content={"error": "Offline STT disabled. Set ROBOT_WHISPER=on."},
        )
    import tempfile
    from pathlib import Path

    model = _whisper_model()

    suffix = Path(audio.filename or "clip.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await audio.read())
        path = tmp.name

    segments, _info = model.transcribe(path, beam_size=1, vad_filter=True)
    text = " ".join(s.text.strip() for s in segments).strip()
    Path(path).unlink(missing_ok=True)
    return {"text": text}


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

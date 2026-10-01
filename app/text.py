"""Tokenising, chunking and sentence splitting. Pure stdlib, no NLTK."""

import re
from pathlib import Path

from .config import CHUNK_OVERLAP_WORDS, CHUNK_WORDS

STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being", "am",
    "do", "does", "did", "of", "to", "in", "on", "at", "for", "with", "and",
    "or", "but", "if", "then", "than", "so", "as", "by", "from", "that",
    "this", "these", "those", "it", "its", "we", "our", "you", "your", "i",
    "me", "my", "he", "she", "they", "them", "there", "here", "what", "which",
    "who", "whom", "how", "when", "where", "why", "can", "could", "should",
    "would", "will", "shall", "may", "might", "must", "have", "has", "had",
    "about", "into", "over", "under", "please", "tell", "give", "much",
    "many", "any", "some", "like", "want", "need", "know", "get", "got",
}

# Question words are NOT stopwords here. "who founded Arnobot" and "when was
# Arnobot founded" share every other term, so dropping the wh-word makes the
# two questions identical and the wrong section can win. Their IDF is low, so
# they nudge rather than dominate.
for _wh in ("who", "when", "where", "which", "what", "how", "why", "whom"):
    STOPWORDS.discard(_wh)

_WORD = re.compile(r"[a-z0-9]+")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])|\n+")
# "also: where are you based, which city" — extra phrasings for a section.
# Indexed for matching, never spoken back as part of the answer.
_ALIAS = re.compile(r"^(?:also|keywords?|aliases?)\s*:\s*(.+)$", re.IGNORECASE)


def tokenize(text: str, keep_stopwords: bool = False) -> list[str]:
    words = _WORD.findall(text.lower())
    if keep_stopwords:
        return words
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def sentences(text: str) -> list[str]:
    parts = [s.strip(" \t-•") for s in _SENT.split(text) if s and s.strip()]
    return [p for p in parts if p]


def _flush(
    buf: list[str], heading: str, source: str, out: list[dict], aliases: str = ""
) -> None:
    body = " ".join(buf).strip()
    if not body:
        return
    words = body.split()
    step = max(1, CHUNK_WORDS - CHUNK_OVERLAP_WORDS)
    for start in range(0, len(words), step):
        window = words[start : start + CHUNK_WORDS]
        if not window:
            break
        out.append(
            {
                "source": source,
                "heading": heading,
                "text": " ".join(window),
                "aliases": aliases,
            }
        )
        if start + CHUNK_WORDS >= len(words):
            break


def chunk_markdown(text: str, source: str) -> list[dict]:
    """Split on headings first, then into overlapping word windows.

    The heading path travels with the chunk so a retrieved fragment still
    carries its topic ("Support > Working hours") into the answer.
    """
    out: list[dict] = []
    stack: list[str] = []
    buf: list[str] = []
    aliases = ""

    # <!-- comments --> are notes for whoever edits the file, never knowledge
    # (data/web/arnobot_in.md carries its sources and sync time in one).
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)

    for raw in text.splitlines():
        line = raw.rstrip()
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            _flush(buf, " > ".join(stack), source, out, aliases)
            buf = []
            aliases = ""
            level = len(m.group(1))
            stack = stack[: level - 1]
            stack.append(m.group(2).strip())
            continue
        alias_match = _ALIAS.match(line.strip())
        if alias_match:
            aliases = f"{aliases} {alias_match.group(1)}".strip()
            continue
        if not line.strip():
            # Blank line inside a section: keep accumulating, the word-window
            # splitter handles size. Q/A blocks stay glued to their answer.
            buf.append("")
            continue
        buf.append(line.strip())

    _flush(buf, " > ".join(stack), source, out, aliases)
    return out


def load_documents(data_dir: Path) -> list[dict]:
    """Read every .md / .txt / .json file under data/ into chunks."""
    chunks: list[dict] = []
    if not data_dir.exists():
        return chunks

    for path in sorted(data_dir.rglob("*")):
        if path.suffix.lower() not in {".md", ".txt", ".json"}:
            continue
        source = str(path.relative_to(data_dir)).replace("\\", "/")
        raw = path.read_text(encoding="utf-8", errors="replace")

        if path.suffix.lower() == ".json":
            chunks.extend(_chunks_from_json(raw, source))
        else:
            chunks.extend(chunk_markdown(raw, source))

    return chunks


def _chunks_from_json(raw: str, source: str) -> list[dict]:
    """Accept a list of {question, answer} or {title, text} records."""
    import json

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return chunk_markdown(raw, source)

    records = payload if isinstance(payload, list) else payload.get("items", [])
    out = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        heading = str(rec.get("question") or rec.get("title") or "").strip()
        body = str(rec.get("answer") or rec.get("text") or rec.get("body") or "").strip()
        if not body:
            continue
        extra = rec.get("aliases") or rec.get("keywords") or []
        out.append(
            {
                "source": source,
                "heading": heading,
                "text": body,
                "aliases": " ".join(extra) if isinstance(extra, list) else str(extra),
            }
        )
    return out

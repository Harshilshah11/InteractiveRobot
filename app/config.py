"""Central configuration. Everything is overridable by environment variable."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
WEB_DIR = ROOT / "web"
DB_PATH = Path(os.getenv("ROBOT_DB", ROOT / "store" / "knowledge.db"))

# Retrieval ------------------------------------------------------------------
# How many chunks come back from each retriever before fusion.
TOP_K = int(os.getenv("ROBOT_TOP_K", "5"))

# Confidence below this -> the robot will not state an answer. It never
# guesses. 0.0 = answer anything, 1.0 = answer nothing.
THRESHOLD = float(os.getenv("ROBOT_THRESHOLD", "0.42"))

# Between CLARIFY_THRESHOLD and THRESHOLD the robot asks instead of answering:
# it found something related but not close enough to say out loud, so it offers
# the nearest questions it *can* answer. Below it, there is nothing useful to
# offer and the answer is a referral to the team.
CLARIFY_THRESHOLD = float(os.getenv("ROBOT_CLARIFY_THRESHOLD", "0.22"))

# A one-word question like "battery" scores high — its single content word is
# covered perfectly — while being genuinely unanswerable, because it does not
# say which robot or whether you mean the spec or the charging routine. When
# rival sections score within this margin of the winner AND disagree about
# their subject, the score is high for the wrong reason and the robot asks.
AMBIGUITY_MARGIN = float(os.getenv("ROBOT_AMBIGUITY_MARGIN", "0.06"))

# ...but only when the question is made of words the knowledge base knows.
# "what is Google's revenue" also lands in the clarify band, and offering to
# rephrase it would be a lie — the answer is not here at any phrasing. A
# question carrying unknown words is out of scope, not badly worded.
CLARIFY_MAX_OOV = float(os.getenv("ROBOT_CLARIFY_MAX_OOV", "0.20"))

# Confidence = STRONG_WEIGHT * (best of semantic/keyword evidence)
#            + (1 - STRONG_WEIGHT) * (the weaker one).
# Lower it to demand that both signals agree before answering.
STRONG_WEIGHT = float(os.getenv("ROBOT_STRONG_WEIGHT", "0.85"))

# How hard to penalise question words that appear nowhere in the knowledge
# base. This is what stops "how much does Saibya cost" from being answered
# with Saibya's dimensions. 0 disables the check.
OOV_PENALTY = float(os.getenv("ROBOT_OOV_PENALTY", "0.85"))

# Where to send anyone the knowledge base cannot help. Kept in one place so
# the number and address are never restated inconsistently.
CONTACT = os.getenv(
    "ROBOT_CONTACT", "call +91 99255 12860 or email contact@arnobot.in"
)

# A refusal that ends the conversation is a worse product than one that hands
# the caller on. The guarantee is unchanged — the robot still states no fact it
# cannot ground — but it now says who can answer instead.
FALLBACK = os.getenv(
    "ROBOT_FALLBACK",
    "I do not have that in my knowledge base. Please contact the Arnobot team "
    f"— {CONTACT} — and they will be able to explain.",
)

# Conversational turns that are not questions. Each one answers in kind and
# then re-opens the floor — a reply that closes the conversation is a dead end
# whatever it is replying to.
GREETING = os.getenv(
    "ROBOT_GREETING",
    "Hello. I am Arnobot's assistant. Ask me about the company, our robots, "
    "or how to get in touch.",
)
THANKS_REPLY = os.getenv(
    "ROBOT_THANKS", "You are welcome. Is there anything else I can tell you?"
)
# Closes the conversation, and has to read naturally for both an explicit
# "goodbye" and a declined offer of more help ("no thanks"). It asks nothing,
# which is the point — a farewell that ends in a question does not end.
FAREWELL = os.getenv(
    "ROBOT_FAREWELL",
    f"Thank you for your time. The Arnobot team is on {CONTACT} whenever you "
    "need them.",
)
ACK_REPLY = os.getenv(
    "ROBOT_ACK", "What else would you like to know about Arnobot?"
)

# Spoken once after an answer if the room goes quiet, then not again until the
# next answer. Long enough that it never talks over someone still reading.
CLOSING = os.getenv(
    "ROBOT_CLOSING",
    "Thank you. Ask me anything else about Arnobot whenever you are ready.",
)
CLOSING_DELAY_MS = int(os.getenv("ROBOT_CLOSING_DELAY_MS", "25000"))

# Opening line when the robot has a near miss rather than a match.
CLARIFY_PREFIX = os.getenv(
    "ROBOT_CLARIFY_PREFIX",
    "I am not sure I understood that. Could you repeat it, or try one of these",
)

# An overview answer stitches several sections together, so it needs a longer
# budget than a single-fact reply — but it is still spoken aloud, so it cannot
# run on. Roughly 45 seconds of speech.
PROFILE_MAX_CHARS = int(os.getenv("ROBOT_PROFILE_MAX_CHARS", "820"))

# Embeddings -----------------------------------------------------------------
# ONNX model, ~130 MB, downloaded once then runs fully offline on CPU.
# Set ROBOT_EMBEDDINGS=off to run keyword-only (zero download).
EMBED_MODEL = os.getenv("ROBOT_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
EMBEDDINGS_ENABLED = os.getenv("ROBOT_EMBEDDINGS", "on").lower() != "off"

# Chunking -------------------------------------------------------------------
CHUNK_WORDS = int(os.getenv("ROBOT_CHUNK_WORDS", "110"))
CHUNK_OVERLAP_WORDS = int(os.getenv("ROBOT_CHUNK_OVERLAP", "25"))

# Optional local phrasing model (Ollama). Off by default — the extractive
# answerer already returns grounded text and cannot hallucinate.
OLLAMA_ENABLED = os.getenv("ROBOT_OLLAMA", "off").lower() == "on"
OLLAMA_URL = os.getenv("ROBOT_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("ROBOT_OLLAMA_MODEL", "qwen2.5:1.5b-instruct")

# Optional offline speech-to-text (faster-whisper). Off by default — the
# browser's own recogniser needs no install.
WHISPER_ENABLED = os.getenv("ROBOT_WHISPER", "off").lower() == "on"
WHISPER_MODEL = os.getenv("ROBOT_WHISPER_MODEL", "tiny.en")

HOST = os.getenv("ROBOT_HOST", "127.0.0.1")
PORT = int(os.getenv("ROBOT_PORT", "8000"))

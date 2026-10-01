"""Turn retrieved context into a short spoken answer.

Default mode is extractive: the reply is assembled from sentences that are
literally present in your data, so hallucination is structurally impossible —
there is no generative model in the path. An optional local Ollama pass only
rephrases those same sentences and is off unless you turn it on.

Three things happen on top of plain extraction, and all three are decided
*after* the confidence gate, never instead of it:

1. A product question gets a **profile** — what it is, what it carries, what it
   can do, what it is for — stitched from that product's own sections rather
   than three sentences of whichever one section ranked highest.
2. A near miss gets a **clarification** instead of a flat no: the robot offers
   the closest questions it can actually answer.
3. Anything genuinely outside the knowledge base gets a **referral** to the
   Arnobot team, rather than a dead end.
"""

from __future__ import annotations

import re

from . import products, smalltalk
from .config import (
    ACK_REPLY,
    AMBIGUITY_MARGIN,
    CLARIFY_MAX_OOV,
    CLARIFY_PREFIX,
    CLARIFY_THRESHOLD,
    FALLBACK,
    FAREWELL,
    GREETING,
    OLLAMA_ENABLED,
    OLLAMA_MODEL,
    OLLAMA_URL,
    PROFILE_MAX_CHARS,
    SITE_THRESHOLD,
    THANKS_REPLY,
    THRESHOLD,
)
from .retriever import stem
from .text import sentences, tokenize

MAX_SENTENCES = 3
MAX_CHARS = 420

# How much of each section a profile is allowed to read, and in what order.
# Tuned so all four products fit inside PROFILE_MAX_CHARS with their use cases
# still attached: an earlier split spent the whole budget on the overview and
# specifications, and every profile got cut off before saying what the robot is
# actually for. Payload lives in the third specification sentence, which is why
# that section gets three.
PROFILE_PLAN = {"overview": 2, "specs": 3, "features": 1, "uses": 1}


def _score_sentence(sentence: str, query_terms: set[str], position: int) -> float:
    tokens = {stem(t) for t in tokenize(sentence)}
    if not tokens:
        return 0.0
    overlap = len(query_terms & tokens)
    # Slight bias to earlier sentences: definitions tend to lead a section.
    return overlap + max(0.0, 0.35 - position * 0.05)


def _body(chunk: dict) -> str:
    """Chunk text with a repeated heading stripped off the front."""
    body = chunk["text"]
    heading = (chunk.get("heading") or "").split(">")[-1].strip()
    if heading and body.lower().startswith(heading.lower()):
        stripped = body[len(heading) :].strip(" :-–—")
        if stripped:
            return stripped
    return body


def _extract(question: str, chunk: dict) -> str:
    query_terms = {stem(t) for t in tokenize(question)}
    parts = sentences(_body(chunk))
    if not parts:
        return _body(chunk).strip()

    ranked = sorted(
        ((_score_sentence(s, query_terms, i), i, s) for i, s in enumerate(parts)),
        key=lambda x: (-x[0], x[1]),
    )

    if ranked[0][0] <= 0:
        # No sentence matched a query word — read the section from the top
        # rather than picking an arbitrary middle sentence.
        picked = list(range(min(MAX_SENTENCES, len(parts))))
    else:
        picked = sorted(
            idx for score, idx, _text in ranked[:MAX_SENTENCES] if score > 0
        ) or [ranked[0][1]]

    answer, used = [], 0
    for i in picked:
        sentence = parts[i].strip()
        if used + len(sentence) > MAX_CHARS and answer:
            break
        answer.append(sentence)
        used += len(sentence)

    return _finish(" ".join(answer))


def _finish(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _lead(chunk: dict, limit: int) -> list[str]:
    """The first `limit` sentences of a section, which is its summary."""
    return [s.strip() for s in sentences(_body(chunk))[:limit] if s.strip()]


def _profile(product_key: str, retriever) -> str:
    """Explain a product the way a person would: what, how big, what it does.

    Reads that product's own sections by name. Retrieval has already decided
    the question is about this product and cleared the confidence gate; this
    only decides how completely to answer it.
    """
    if retriever is None:
        return ""

    out: list[str] = []
    used = 0
    for facet, limit in PROFILE_PLAN.items():
        heading = products.PRODUCTS[product_key]["sections"].get(facet)
        chunk = retriever.section(heading) if heading else None
        if not chunk:
            continue
        for sentence in _lead(chunk, limit):
            if used + len(sentence) > PROFILE_MAX_CHARS and out:
                return _finish(" ".join(out))
            out.append(sentence)
            used += len(sentence)
    return _finish(" ".join(out))


def _named_section(product_key: str, facet: str, question: str, retriever) -> str:
    """Answer a specific facet from that product's own section.

    Retrieval ranks by similarity to the whole question, so "how much can NEXUS
    carry" can land on the overview when the specifications section is what was
    asked for. When the question names a product *and* a facet, read the
    section that actually holds the fact.
    """
    if retriever is None:
        return ""
    heading = products.PRODUCTS[product_key]["sections"].get(facet)
    chunk = retriever.section(heading) if heading else None
    return _extract(question, chunk) if chunk else ""


def _better_covered(question: str, key: str, facet: str, fallback: str, retriever) -> str:
    """Pick between two of a product's sections by what their text contains.

    Ties go to `fallback`, the section retrieval chose: the cue list only wins
    when it can show the words to back it up.
    """
    sections = products.PRODUCTS[key]["sections"]
    if retriever is None or facet not in sections:
        return fallback
    candidate = retriever.section(sections[facet])
    chosen = retriever.section(sections[fallback])
    if not candidate or not chosen:
        return fallback
    return (
        facet
        if retriever.covers(question, candidate) > retriever.covers(question, chosen)
        else fallback
    )


def _compose(question: str, best: dict, retriever) -> tuple[str, list[str], str]:
    """Build the reply. Returns (text, followups, facet)."""
    named = products.detect_products(question)
    facet = products.detect_facet(question)

    # Two products named — that is a comparison, not a profile. Read whichever
    # comparison section retrieval found and offer both products next.
    if len(named) > 1:
        text = _extract(question, best)
        follow = [f"Tell me about {products.PRODUCTS[k]['name']}" for k in named[:3]]
        return text, follow, "compare"

    if len(named) == 1:
        key = named[0]
        sections = products.PRODUCTS[key]["sections"]
        won = (best.get("heading") or "").split(">")[-1].strip().lower()
        won_facet = next((f for f, h in sections.items() if h.lower() == won), None)

        if won_facet is None:
            # Retrieval did not land on any of this product's own pages, so it
            # found something better than a datasheet — pricing, autonomy, an
            # operating procedure. "How much does Saibya cost" is a pricing
            # question that happens to name a robot, and answering it with the
            # robot's dimensions is the exact failure this guards against.
            return (
                _extract(question, best),
                products.followups_for_heading(best.get("heading", "")),
                "general",
            )

        if facet == "overview":
            text = _profile(key, retriever) or _extract(question, best)
            return text, products.followups_for_product(key, "overview"), "overview"

        # The overview is a magnet — it matches on the product name alone, so a
        # facet question can land there while the fact lives in the section
        # next door.
        if won_facet == "overview":
            target = facet
        elif facet != won_facet:
            # Cue and retrieval disagree about which section to read. Neither
            # is authoritative, so let the text settle it: whichever section
            # actually contains more of the question's rare words has the fact.
            # "What tyres does ATM use" reads as a use-case question and is a
            # specification one — only the specifications say "tyres".
            target = _better_covered(question, key, facet, won_facet, retriever)
        else:
            target = won_facet
        text = _named_section(key, target, question, retriever) or _extract(
            question, best
        )
        return text, products.followups_for_product(key, target), target

    # No product named. "What robots do you make" still deserves the four
    # products as follow-ups; anything else follows its own topic.
    text = _extract(question, best)
    if products.is_range_question(question) or products.is_comparison(question):
        follow = list(products.RANGE_FOLLOWUPS)[:4]
    else:
        follow = products.followups_for_heading(best.get("heading", ""))
    return text, follow, "general"


WH_WORDS = {"who", "when", "where", "which", "what", "how", "why", "whom"}


def _matches_alias(question: str, chunk: dict) -> bool:
    """True when the question is verbatim one of the section's `also:` phrases."""
    asked = smalltalk.normalise(question)
    if not asked:
        return False
    return any(
        smalltalk.normalise(phrase) == asked
        for phrase in (chunk.get("aliases") or "").split(",")
    )


def _is_ambiguous(question: str, hits: list[dict]) -> bool:
    """True when the winning score is high but not for a trustworthy reason.

    Three conditions, all required:

    * **No product named.** "NEXUS battery" has one subject however many NEXUS
      sections tie for it.
    * **One content word or fewer.** "Battery" covers 100% of its own content
      words, so it scores like a confident match against every section that
      mentions a battery. "Which city are you based in" carries enough to pin
      a subject, and asking it to rephrase would be obtuse.
    * **The tied sections disagree about their subject.** Four NEXUS sections
      scoring alike is a well-understood question, not a confused one.
    """
    if len(hits) < 2 or products.detect_products(question):
        return False

    # The `also:` line is the author saying "this exact phrasing means this
    # section". If they anticipated the wording, honour it — "what can you do"
    # is thin by every other measure and still has one right answer.
    if _matches_alias(question, hits[0]):
        return False

    # Question words are excluded: they say what shape of answer is wanted, not
    # what it is about, so "how many" is every bit as thin as "many".
    content = [t for t in tokenize(question) if t not in WH_WORDS]
    if len(content) > 1:
        return False

    cutoff = hits[0]["confidence"] - AMBIGUITY_MARGIN
    tied = [h for h in hits if h["confidence"] >= cutoff]
    subjects = {products.subject_of(h.get("heading", "")) for h in tied}
    return len(subjects) > 1


def _clarify(question: str, hits: list[dict]) -> dict:
    """Near miss: offer the closest answerable questions instead of guessing."""
    candidates: list[str] = []
    for hit in hits[:5]:
        label = products.question_for_heading(hit.get("heading", ""))
        if label and label not in candidates:
            candidates.append(label)
    suggestions = products.prune(candidates, question)
    if not suggestions:
        return _refer(hits[0]["confidence"] if hits else 0.0)

    spoken = "; ".join(s.rstrip("?") for s in suggestions)
    return {
        "answer": f"{CLARIFY_PREFIX}: {spoken}?",
        "answered": False,
        "mode": "clarify",
        "confidence": hits[0]["confidence"],
        "followups": suggestions,
        "sources": [],
    }


def _chat(kind: str) -> dict:
    """Answer a turn that was not a question, and re-open the floor."""
    text = {
        "greet": GREETING,
        "thanks": THANKS_REPLY,
        "bye": FAREWELL,
        "ack": ACK_REPLY,
    }[kind]
    # A greeting is the one moment the whole range is the right thing to
    # offer; the rest are mid-conversation and get the standing suggestions.
    follow = (
        list(products.RANGE_FOLLOWUPS)
        if kind == "greet"
        else list(products.DEFAULT_FOLLOWUPS)
    )
    return {
        "answer": text,
        "answered": False,
        "mode": "chat",
        "kind": kind,
        "confidence": 0.0,
        "followups": follow,
        "sources": [],
    }


def _refer(confidence: float) -> dict:
    return {
        "answer": FALLBACK,
        "answered": False,
        "mode": "refer",
        "confidence": confidence,
        "followups": list(products.DEFAULT_FOLLOWUPS),
        "sources": [],
    }


def _polish_with_ollama(question: str, context: str) -> str | None:
    """Optional. Rephrases the extracted context; adds nothing to it."""
    try:
        import json
        import urllib.request

        prompt = (
            "Rewrite the CONTEXT into one short spoken answer to the QUESTION. "
            "Use only facts in the CONTEXT. Add nothing. No preamble.\n\n"
            f"CONTEXT:\n{context}\n\nQUESTION: {question}\n\nANSWER:"
        )
        payload = json.dumps(
            {
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 220},
            }
        ).encode()
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            text = json.loads(resp.read())["response"].strip()
        return re.sub(r"\s+", " ", text) or None
    except Exception:
        return None  # any failure falls back to the extractive answer


def respond(question: str, retriever) -> dict:
    """The whole turn: small talk, then retrieval, then the gate.

    One entry point so the route and the test suite exercise the same path —
    a small-talk rule that only the server applies is a rule the tests cannot
    catch when it starts swallowing real questions.
    """
    kind, cleaned = smalltalk.detect(question)
    if kind:
        return _chat(kind)

    hits = retriever.search(cleaned)
    _promote_exact_alias(cleaned, hits)
    result = answer(cleaned, hits, retriever)

    # company.md had nothing confident to say. Before referring the caller on
    # (or asking them to rephrase), see whether the website says it.
    if not result["answered"] and result["mode"] in {"refer", "clarify"}:
        site = _from_site(cleaned, getattr(retriever, "site", None))
        if site:
            return site
    return result


def _from_site(question: str, site) -> dict | None:
    """Answer from the synced copy of arnobot.in, or None.

    Same rules as the main path — a verbatim sentence or nothing — with a
    higher bar: the stricter threshold, and a question with at least two
    content words, since a one-word question ("features") matches every
    product page equally and is a clarification, not a lookup.
    """
    if site is None or not site.chunks:
        return None
    content = [t for t in tokenize(question) if t not in WH_WORDS]
    if len(content) < 2:
        return None

    hits = site.search(question)
    _promote_exact_alias(question, hits)
    if not hits or hits[0]["confidence"] < SITE_THRESHOLD:
        return None

    best = hits[0]
    text = _extract(question, best)
    if not text:
        return None
    if OLLAMA_ENABLED:
        text = _polish_with_ollama(question, text) or text

    named = products.detect_products(question)
    followups = (
        products.followups_for_product(named[0], "overview")
        if len(named) == 1
        else list(products.DEFAULT_FOLLOWUPS)
    )
    return {
        "answer": text,
        "answered": True,
        "mode": "answer",
        "facet": "site",
        "origin": "arnobot.in",
        "confidence": best["confidence"],
        "followups": products.prune(followups, question),
        "sources": [
            {
                "source": h["source"],
                "heading": h["heading"],
                "confidence": h["confidence"],
                "snippet": h["text"][:220],
            }
            for h in hits[:3]
        ],
    }


def _promote_exact_alias(question: str, hits: list[dict]) -> bool:
    """Move a section whose `also:` line contains this exact wording to the front.

    Retrieval scores "what can you do" identically (0.88) against the section
    written for that question and against Saibya's do-not list, because after
    stopwords the question is one word long and both sections carry it. A
    phrasing the author wrote down beats a coin toss.

    Reordering only — the confidence gate still runs. An authored phrase that
    cannot clear the threshold is a data problem worth seeing, not something
    to wave through.
    """
    for i, hit in enumerate(hits):
        if _matches_alias(question, hit):
            if i:
                hits.insert(0, hits.pop(i))
            return True
    return False


def answer(question: str, hits: list[dict], retriever=None) -> dict:
    """Gate first, then compose. Never the other way round."""
    if not hits:
        return _refer(0.0)

    best = hits[0]
    confidence = best["confidence"]

    if confidence < THRESHOLD:
        # Related-but-not-sure only counts when every word of the question is
        # one the knowledge base uses. An unknown word means the fact is
        # missing, not that the phrasing was unlucky, and no rewording of
        # "what is Google's revenue" will ever make it answerable here.
        if confidence >= CLARIFY_THRESHOLD and best.get("oov", 0.0) <= CLARIFY_MAX_OOV:
            return _clarify(question, hits)
        return _refer(confidence)

    # Confident enough to speak — but confident about what? A question too
    # thin to pick a subject scores high against several at once, and picking
    # one of them at random is a worse answer than admitting the ambiguity.
    if _is_ambiguous(question, hits):
        return _clarify(question, hits)

    text, followups, facet = _compose(question, best, retriever)

    if OLLAMA_ENABLED and text:
        polished = _polish_with_ollama(question, text)
        if polished:
            text = polished

    if not text:
        return _refer(confidence)

    return {
        "answer": text,
        "answered": True,
        "mode": "answer",
        "facet": facet,
        "confidence": confidence,
        "followups": products.prune(followups, question, max(3, len(followups))),
        "sources": [
            {
                "source": h["source"],
                "heading": h["heading"],
                "confidence": h["confidence"],
                "snippet": h["text"][:220],
            }
            for h in hits[:3]
        ],
    }

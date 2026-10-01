"""Product-aware reasoning: which robot, which facet, what to offer next.

This module is the "salesperson" layer. Retrieval alone answers the question
that was asked; a person explaining a product also decides *what else* the
listener needs to hear — payload, features, where it is used — and offers the
obvious next question.

Nothing here generates text about the robots. It only decides which indexed
sections the answerer should read, in what order, and which follow-up
questions to offer. Every fact still comes out of data/company.md, so the
no-hallucination guarantee is untouched.
"""

from __future__ import annotations

import re

# Facets, in the order a person would naturally explain a machine: what it is,
# how big/strong it is, what it can do, what it is for, who buys it.
FACETS = ("overview", "specs", "features", "uses", "industries")

# heading suffix per facet — these must match the "## ..." lines in the data.
PRODUCTS: dict[str, dict] = {
    "saibya": {
        "name": "Saibya",
        # `kind` is a display label for the product cards, not a fact the robot
        # states. It mirrors the categories already written in the "Product
        # range" section; no figures live here, so a card can never go stale
        # against the data. Every number still comes from data/company.md.
        "kind": "Unmanned ground vehicle",
        # Speech recognisers mangle unfamiliar proper nouns, so accept the
        # spellings the browser actually returns, not just the correct one.
        "terms": ("saibya", "sabya", "saibhya", "sabhya", "sibya", "saiba"),
        "sections": {
            "overview": "Saibya overview",
            "specs": "Saibya specifications",
            "features": "Saibya features",
            "uses": "Saibya use cases",
            "industries": "Saibya industries",
        },
        # Beyond the five facets: shown as its own tab in the showcase. Each
        # attachment has its own section in the data (short sections retrieve
        # cleanly); a card shows that section's text, the data's own wording.
        "extras": {"attachments": "Saibya attachments"},
        "attachment_cards": [
            {"title": "Surveillance", "image": "attach-surveillance.webp", "heading": "Saibya surveillance attachment"},
            {"title": "Gun mounting", "image": "attach-gun-mount.webp", "heading": "Saibya gun mounting attachment"},
            {"title": "Payload carrying", "image": "attach-payload.webp", "heading": "Saibya payload carrying attachment"},
            {"title": "Grass cutting", "image": "attach-grass-cutting.webp", "heading": "Saibya grass cutting attachment"},
            {"title": "Mine dispensing", "image": "attach-mine-dispensing.webp", "heading": "Saibya mine dispensing attachment"},
        ],
    },
    "atm": {
        "name": "ATM",
        "kind": "Any Terrain Machine",
        "terms": ("atm", "any terrain machine", "a t m"),
        "sections": {
            "overview": "ATM overview",
            "specs": "ATM specifications",
            "features": "ATM features",
            "uses": "ATM use cases",
            "industries": "ATM industries",
        },
    },
    "nexus": {
        "name": "NEXUS",
        "kind": "Nano exploration robot",
        "terms": ("nexus", "nexis", "nexsus", "nano exploration"),
        "sections": {
            "overview": "NEXUS overview",
            "specs": "NEXUS specifications",
            "features": "NEXUS features",
            "uses": "NEXUS use cases",
            "industries": "NEXUS industries",
        },
    },
    "altius": {
        "name": "Altius",
        "kind": "Vertical climbing robot",
        "terms": ("altius", "altious", "altus", "alteus"),
        "sections": {
            "overview": "Altius overview",
            "specs": "Altius specifications",
            "features": "Altius features",
            "uses": "Altius use cases",
            "industries": "Altius industries",
        },
    },
}

# Phrases that mean "which facet of the product are you asking about". Checked
# as substrings of the raw question: multi-word cues like "used for" carry far
# more signal than either word alone.
FACET_CUES: dict[str, tuple[str, ...]] = {
    "specs": (
        "spec", "dimension", "size", "how big", "how small", "weight",
        "how heavy", "payload", "how much can", "carry", "capacity", "load",
        "battery", "power", "voltage", "clearance", "speed", "runtime",
        "how long does", "charge", "charging time", "camera", "tyre", "tire",
        "range", "technical", "ip rating", "waterproof", "temperature",
    ),
    "features": (
        "feature", "capability", "capabilities", "what can", "can it",
        "does it have", "able to", "strength", "advantage", "special",
        "why should", "what makes",
    ),
    "uses": (
        "use case", "used for", "use for", "using", "application", "task",
        "job", "mission", "purpose", "what is it for", "what do you do with",
        "good for", "suitable for", "can i use",
    ),
    "industries": (
        "industry", "industries", "sector", "who uses", "who buys",
        "customer", "market", "deployed", "where is it used",
        "where can it be used", "vertical", "domain", "client",
    ),
}

# "list me your products" — no single product named, but clearly a product ask.
RANGE_CUES = (
    "product", "products", "robots", "range", "portfolio", "catalogue",
    "catalog", "lineup", "line up", "what do you make", "what do you build",
    "what do you offer", "what do you sell", "how many robot",
    "how many product", "platforms", "machines",
)

COMPARE_CUES = ("compare", "comparison", " vs ", "versus", "difference between",
                "which robot", "which one", "better", "recommend")

# Follow-ups for the parts of the knowledge base that are not product pages.
# Keyed on the top-level heading the winning chunk sits under.
TOPIC_FOLLOWUPS: dict[str, tuple[str, ...]] = {
    "Arnobot": (
        "What products do you make?",
        "Who are the founders?",
        "Where are you located?",
    ),
    "Founders": (
        "How large is the team?",
        "What products do you make?",
        "When was the company founded?",
    ),
    "Products": (
        "Which robot should I choose?",
        "Can I get a demo?",
    ),
    "Company track record": (
        "Which industries do you serve?",
        "Where have your robots been deployed?",
        "Can I get a demo?",
    ),
    "NEXUS operation": (
        "What are NEXUS specifications?",
        "What is NEXUS used for?",
        "Which industries use NEXUS?",
    ),
    "Saibya operation": (
        "What are Saibya specifications?",
        "What is Saibya used for?",
        "Which industries use Saibya?",
    ),
}

DEFAULT_FOLLOWUPS = (
    "What robots do you make?",
    "Which industries do you serve?",
    "Can I get a demo?",
)

RANGE_FOLLOWUPS = tuple(f"Tell me about {p['name']}" for p in PRODUCTS.values())

# Canonical phrasing for a follow-up, per facet. Written to match the `also:`
# lines in the data so that clicking a suggestion always lands on its section,
# and phrased the way a visitor would say it out loud — "how much can it carry"
# beats "specifications" for a question someone is about to speak into a mic.
_FOLLOWUP_TEMPLATES = {
    "overview": "Tell me about {name}",
    "specs": "How much can {name} carry?",
    "features": "What can {name} do?",
    "uses": "What is {name} used for?",
    "industries": "Which industries use {name}?",
}

# What to offer after answering each facet: the natural next things to want.
_NEXT_FACETS: dict[str, tuple[str, ...]] = {
    "overview": ("specs", "uses", "industries"),
    "specs": ("features", "uses", "industries"),
    "features": ("specs", "uses", "industries"),
    "uses": ("industries", "specs", "features"),
    "industries": ("uses", "specs", "features"),
}

# Reverse lookup so a retrieved heading can be turned back into a question.
_SECTION_INDEX: dict[str, tuple[str, str]] = {
    heading.lower(): (key, facet)
    for key, product in PRODUCTS.items()
    for facet, heading in product["sections"].items()
}


def _norm(question: str) -> str:
    """Lowercase and pad, so ' vs ' style cues can match at either end."""
    return " " + re.sub(r"[^a-z0-9 ]+", " ", question.lower()).strip() + " "


def detect_products(question: str) -> list[str]:
    """Every product named in the question, in the order they appear."""
    text = _norm(question)
    found: list[tuple[int, str]] = []
    for key, product in PRODUCTS.items():
        positions = [text.find(f" {t} ") for t in product["terms"]]
        hits = [p for p in positions if p >= 0]
        if hits:
            found.append((min(hits), key))
    return [key for _pos, key in sorted(found)]


def detect_facet(question: str) -> str:
    """Which aspect of a product the question is after.

    Checked most specific first: "how much can it carry" is a spec question
    even though "can it" is a features cue, so `specs` is tested before
    `features`. Anything unrecognised is treated as "tell me about it", which
    is the case that gets the full profile.
    """
    text = _norm(question)
    for facet in ("industries", "uses", "specs", "features"):
        if any(cue in text for cue in FACET_CUES[facet]):
            return facet
    return "overview"


def is_range_question(question: str) -> bool:
    """"What do you make" — a product ask with no product named.

    Matched on whole words only: "range" is a cue for the product range, but
    it is also half of "remote control range", and a substring test would call
    that a catalogue question.
    """
    text = _norm(question)
    return any(f" {cue} " in text for cue in RANGE_CUES)


def is_comparison(question: str) -> bool:
    text = _norm(question)
    return any(cue in text for cue in COMPARE_CUES)


def followup_label(product_key: str, facet: str) -> str:
    return _FOLLOWUP_TEMPLATES[facet].format(name=PRODUCTS[product_key]["name"])


def followups_for_product(product_key: str, facet: str, limit: int = 3) -> list[str]:
    out = [followup_label(product_key, nxt) for nxt in _NEXT_FACETS[facet]]
    if facet in ("uses", "industries"):
        out.append("Can I get a demo?")
    return out[:limit]


def followups_for_heading(heading: str, limit: int = 3) -> list[str]:
    """Follow-ups for an answer that was not about one specific product."""
    last = (heading or "").split(">")[-1].strip().lower()
    if last in _SECTION_INDEX:
        key, facet = _SECTION_INDEX[last]
        return followups_for_product(key, facet, limit)

    top = (heading or "").split(">")[0].strip()
    return list(TOPIC_FOLLOWUPS.get(top, DEFAULT_FOLLOWUPS))[:limit]


def subject_of(heading: str) -> str:
    """What a section is *about*, collapsed to one key.

    "Products > NEXUS specifications" and "NEXUS operation > NEXUS charging"
    are both about NEXUS even though they sit in different parts of the file.
    Used to tell a real tie ("battery" matching Saibya and NEXUS equally) from
    a false one ("what is NEXUS" matching four NEXUS sections equally).
    """
    parts = [p.strip() for p in (heading or "").split(">") if p.strip()]
    if not parts:
        return ""
    if parts[-1].lower() in _SECTION_INDEX:
        return _SECTION_INDEX[parts[-1].lower()][0]
    top = parts[0].lower()
    for key, product in PRODUCTS.items():
        if any(top.startswith(term) for term in product["terms"]):
            return key
    return top


def question_for_heading(heading: str) -> str:
    """Turn a retrieved heading back into a question a user might have meant.

    Used by the clarify path: when confidence is too low to answer, the top
    candidates are offered back as questions rather than guessed at.
    """
    last = (heading or "").split(">")[-1].strip()
    if not last:
        return ""
    if last.lower() in _SECTION_INDEX:
        key, facet = _SECTION_INDEX[last.lower()]
        return followup_label(key, facet)

    # "Problem the company solves" reads better mid-sentence as lower case, but
    # "NEXUS charging" and "Saibya maintenance" must keep their capitals — one
    # is an acronym and the other is a name.
    first = last.split(" ")[0]
    is_name = first.lower() in {t for p in PRODUCTS.values() for t in p["terms"]}
    if not is_name and first[1:].islower():
        last = last[0].lower() + last[1:]
    return f"Tell me about {last}"


def prune(followups: list[str], question: str, limit: int = 3) -> list[str]:
    """Drop suggestions that just repeat the question, then top back up.

    Answering "can I get a demo" and then offering "Can I get a demo?" as the
    next thing to ask makes the robot look like it was not listening.
    """
    asked = re.sub(r"[^a-z0-9 ]+", " ", question.lower())
    asked = " ".join(asked.split())

    out: list[str] = []
    for candidate in list(followups) + list(DEFAULT_FOLLOWUPS):
        norm = " ".join(re.sub(r"[^a-z0-9 ]+", " ", candidate.lower()).split())
        if norm and norm != asked and candidate not in out:
            out.append(candidate)
        if len(out) >= limit:
            break
    return out


def section_sentences(markdown: str, heading: str) -> list[str]:
    """The sentences under one `## heading`, verbatim, without its `also:` line.

    Used by the product showcase, so the sheet shows exactly the text the
    robot reads aloud — never a separately written summary that could drift.
    """
    out: list[str] = []
    inside = False
    for line in markdown.splitlines():
        if line.startswith("#"):
            if inside:
                break
            inside = line.lstrip("#").strip().lower() == heading.lower()
            continue
        if not inside:
            continue
        text = line.strip()
        if text and not text.lower().startswith("also:") and not text.startswith("<!--"):
            out.append(text)
    return out


def product_detail(key: str, markdown: str) -> dict:
    """Everything the showcase needs about one robot, read from the data."""
    product = PRODUCTS[key]
    detail = {
        "key": key,
        "name": product["name"],
        "kind": product["kind"],
        "ask": f"Tell me about {product['name']}",
        "sections": {
            facet: section_sentences(markdown, heading)
            for facet, heading in {**product["sections"], **product.get("extras", {})}.items()
        },
        "attachments": _attachment_cards(product, markdown),
    }
    if detail["attachments"]:
        detail["sections"]["attachments"] += [c["text"] for c in detail["attachments"]]
    return detail


def _attachment_cards(product: dict, markdown: str) -> list[dict]:
    cards = []
    for card in product.get("attachment_cards", []):
        text = " ".join(section_sentences(markdown, card["heading"]))
        if text:  # a card whose section was removed from the data is dropped
            cards.append({**{k: v for k, v in card.items() if k != "heading"}, "text": text})
    return cards

"""Greetings, thanks, goodbyes — the turns that are not questions.

Running "hello" through hybrid retrieval produces a confident-looking match
against whatever section happens to share a stopword with it, which is how an
assistant ends up answering "hi" with a battery specification. These turns are
matched before retrieval and answered in kind.

Two rules earn their keep here:

**A negative closes the conversation.** The reply to "thanks" asks whether
there is anything else; if "no" is only an acknowledgement, the assistant
answers it with *another* question and the two of you are stuck in a loop that
has no exit. "No", "no thanks", "nothing else" and "that's it" all end the
turn politely.

**Politeness padding is stripped before matching.** People say "ok thank you"
and "thank you very much", not the dictionary form. Exact matching on the
whole string alone sends both of those to the knowledge base, which has never
heard of them.

The matching stays strict about scope: a phrase counts only as the **whole**
turn, or as a greeting sitting in front of a real question. "Hi" must never
fire on "which robot climbs walls", and "no" must never fire on "no line of
sight range of ATM". Anything unrecognised goes to retrieval untouched —
silence is the safe default for a module that can only ever intercept.
"""

from __future__ import annotations

import re

GREETINGS = {
    "hi", "hii", "hiii", "hello", "helo", "hey", "heya", "yo", "hai",
    "hi there", "hello there", "hey there", "greetings", "namaste", "hola",
    "good morning", "good afternoon", "good evening", "good day",
}

THANKS = {
    "thanks", "thank you", "thank u", "thanku", "thankyou", "thx", "tq",
    "ty", "tysm", "appreciate it", "much appreciated", "cheers", "grateful",
    "thanks for the help", "thank you for the help", "that helps",
    "that was helpful", "helpful",
}

# Everything that means "I am finished". Bare negatives live here too: after
# "is there anything else?", "no" is an exit, not a shrug.
FAREWELLS = {
    "bye", "byee", "bye bye", "goodbye", "good bye", "see you", "see ya",
    "cya", "later", "catch you later", "good night", "exit", "quit", "stop",
    "done", "im done", "i am done", "we are done", "thats it", "that is it",
    "thats all", "that is all", "thats all for now", "nothing else",
    "no more", "no more questions", "no further questions",
    "im good", "i am good", "all good", "im fine", "i am fine",
    "no thanks", "no thank you", "nope thanks", "nothing thanks",
    "no", "nope", "nah", "nothing", "none", "negative", "not now",
    "not really", "no need",
}

# Acknowledgements: still here, nothing asked. The reply re-opens the floor,
# which is only safe because the negatives above are handled as exits.
ACKS = {
    "ok", "okay", "k", "kk", "fine", "alright", "all right", "sure",
    "nice", "cool", "great", "good", "awesome", "wow", "perfect", "lovely",
    "got it", "understood", "i see", "makes sense", "hmm", "hm", "right",
    "correct", "interesting", "yeah", "yep", "yes", "yup", "yess", "true",
}

# Checked in this order: "no thanks" is a goodbye, not a thank-you.
KINDS = ("bye", "thanks", "greet", "ack")
_SETS = {"greet": GREETINGS, "thanks": THANKS, "bye": FAREWELLS, "ack": ACKS}

# Padding people put around the real phrase. Stripped only after the whole
# string has failed to match, so a bare "ok" is still an acknowledgement.
_LEAD = (
    "ok", "okay", "kk", "alright", "all right", "well", "so", "and", "but",
    "um", "uh", "oh", "ah", "hey", "yeah", "yes", "please", "just",
)
_TAIL = (
    "very much", "so much", "a lot", "a ton", "again", "please", "sir",
    "maam", "madam", "mam", "mate", "buddy", "man", "bro", "dear", "ji",
    "for now", "for the help", "for your help", "for that",
)

# Longest first, so "good morning" is stripped whole rather than leaving a
# stray "morning" in front of the question.
_LEADING_PHRASES = sorted(GREETINGS | THANKS, key=len, reverse=True)


def normalise(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace.

    Apostrophes are deleted rather than replaced with a space, so "that's all"
    normalises to "thats all" and matches — turning it into "that s all" would
    make every contraction unrecognisable.
    """
    lowered = (text or "").lower().replace("'", "").replace("’", "")
    return " ".join(re.sub(r"[^a-z0-9\s]+", " ", lowered).split())


def _classify(text: str) -> str | None:
    for kind in KINDS:
        if text in _SETS[kind]:
            return kind
    return None


def _strip_padding(text: str) -> str:
    """Peel politeness off both ends until nothing more comes away."""
    changed = True
    while changed and text:
        changed = False
        for lead in _LEAD:
            if text.startswith(lead + " "):
                rest = text[len(lead) + 1 :].strip()
                if rest:
                    text, changed = rest, True
                    break
        for tail in _TAIL:
            if text.endswith(" " + tail):
                rest = text[: -(len(tail) + 1)].strip()
                if rest:
                    text, changed = rest, True
                    break
    return text


def detect(question: str) -> tuple[str | None, str]:
    """Classify a turn.

    Returns `(kind, remainder)`:

    * `("greet", "")` — the whole turn was a greeting; answer it as one.
    * `(None, "tell me about saibya")` — a greeting in front of a real
      question. "Hi, what is NEXUS" is a question, and the greeting is noise
      to be stripped rather than a reason to reply "Hello".
    * `(None, original)` — not small talk at all; retrieval takes it.
    """
    text = normalise(question)
    if not text:
        return None, question

    # Whole string first: a bare "ok" must stay an acknowledgement rather than
    # being stripped to nothing by its own entry in the padding list.
    kind = _classify(text)
    if kind:
        return kind, ""

    kind = _classify(_strip_padding(text))
    if kind:
        return kind, ""

    # A greeting or a thank-you can prefix a genuine question.
    for phrase in _LEADING_PHRASES:
        if text.startswith(phrase + " "):
            rest = text[len(phrase) + 1 :].strip()
            if rest:
                return None, rest

    return None, question

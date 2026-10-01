"""Accuracy check against data/company.md.

Run:  python test_answers.py

Four lists, and the last three matter as much as the first. A context-only bot
is judged by what it declines to state, whether it admits an ambiguous question
is ambiguous, and whether it leaves the caller somewhere to go next.
"""

from app import store
from app.answerer import respond
from app.config import CLARIFY_THRESHOLD, THRESHOLD
from app.ingest import build
from app.products import PRODUCTS
from app.retriever import Retriever

SHOULD_ANSWER = [
    # company
    ("what does Arnobot do", "robot"),
    ("when was the company founded", "2024"),
    ("which city are you based in", "Ahmedabad"),
    ("how do I contact you", "arnobot"),
    ("what is your mission", "mission"),
    ("how many people work at Arnobot", "seven"),
    ("how many robots can you build in a month", "month"),
    # founders
    ("who is the CEO", "Anmol Shah"),
    ("who is the CTO", "Anil Maity"),
    ("who is the director", "Amit Shah"),
    ("who founded the company", "Anmol Shah"),
    # products
    ("what products do you make", "Saibya"),
    ("how much can Saibya carry", "200"),
    ("what battery does ATM use", "60 volt"),
    ("what does NEXUS stand for", "Nano Exploration"),
    ("what is the range of NEXUS", "300 metres"),
    ("how heavy is Altius", "25 kilograms"),
    ("what is Altius used for", "clean"),
    ("which robot can climb walls", "Altius"),
    ("is Altius waterproof", "IP-65"),
    # ATM detail that only exists in the spec sheet, not the catalogue
    ("what is the IP rating of ATM", "IP 42"),
    ("how long does ATM run", "4 hours"),
    ("what is the remote range of ATM", "kilometre"),
    ("what tyres does ATM use", "AT18"),
    ("what is ATM made of", "mild steel"),
    # per-product industries — "which industry is this useful for"
    ("which industries use Altius", "maritime"),
    ("which industries use Saibya", "defence"),
    ("which industries use NEXUS", "security"),
    ("which industries use ATM", "solar"),
    # choosing between platforms
    ("which robot should I choose", "Choose"),
    ("which robot carries the most", "500"),
    ("difference between Saibya and ATM", "Choose"),
    # track record
    ("have you won any awards", "Maharathi"),
    ("who are your clients", "Stable Dynamics"),
    ("where have your robots been deployed", "pilot"),
    # operation
    ("how do I start Saibya", "MCB"),
    ("what remote does Saibya use", "Jumper T14"),
    ("how far should bystanders stand", "10 met"),
    ("can I use it in the rain", "rain"),
    # Answerable, though not with a figure: the business model lists revenue
    # streams, so reporting them is grounded rather than a leak.
    ("what is your revenue", "product sales"),
    # Pricing is a question a real company bot should handle, not stonewall.
    # It must survive naming a product — the robot has to notice this is a
    # pricing question that mentions Saibya, not a Saibya question.
    ("how much does Saibya cost", "quotation"),
    ("what is Saibya's price in rupees", "quotation"),
    ("what is the price of Altius", "quotation"),
    # Product range must name every platform, not just the first one matched.
    ("what is your product range", "Altius"),
    ("what products do you make", "NEXUS"),
    ("show me the product lineup", "Saibya"),
    # Business questions the source documents don't answer directly, handled
    # with an honest pointer instead of a refusal or an invented fact.
    ("are you hiring", "arnobot.in/career"),
    ("are you hiring right now", "arnobot.in/career"),
    ("how do I apply for a job", "arnobot.in/apply"),
    ("do you offer internships", "AI Research Intern"),
    ("how can I buy", "order"),
    ("can I get a demo", "demo"),
    ("do you export", "contact"),
    ("do you provide support", "contact@arnobot.in"),
    ("are you ISO certified", "ISO"),
    ("what makes you unique", "safety"),
    ("where can I follow you", "LinkedIn"),
    ("can it be automated", "autonomous"),
    # NEXUS manual
    ("how long does NEXUS run", "20 minutes"),
    ("what comes with NEXUS", "SkyDroid"),
    ("how do I charge NEXUS", "2.2 amp"),
    ("NEXUS will not turn on", "recharge"),
    ("what temperature can NEXUS handle", "45 degrees"),
    ("can Saibya climb stairs", "stair"),
    # Saibya's five attachments: each question lands on its own section, and
    # the answer opens on a whole sentence about that attachment.
    ("what attachments does Saibya have", "five attachments"),
    ("tell me about the mine dispensing attachment", "dispenser rails"),
    ("can saibya cut grass", "mower deck"),
    ("can saibya carry a gun", "weapon mount"),
    ("what is the surveillance attachment", "sensor mast"),
    ("does saibya have a hopper", "open hopper"),
    ("how fast is Saibya", "8 kilometres per hour"),
    ("how long does Saibya run", "3 hours"),
    # Website facts (arnobot.in)
    ("which robot can climb walls", "Altius"),
    ("what are your office hours", "10 AM"),
    ("does the robot need internet", "onboard"),
    ("what technology do you use", "autonomy"),
    ("do you have patents", "four"),
    ("can I become a distributor", "partnership"),
    ("what is your mission", "safer"),
    ("what is your vision", "asset lifecycle"),
    ("how much does NEXUS weigh", "3 kilogram"),
    ("what is ATM used for", "towing"),
    ("where are you located", "Satellite Road"),
    ("why use robots instead of manual inspection", "continuous monitoring"),
    ("what is your email", "contact@arnobot.in"),
    ("contact", "99255"),
]

# Asking about a product must produce the key data a buyer needs, not three
# sentences of whichever section happened to rank first. Each entry lists every
# substring the profile has to contain: what it is, what it carries, and what it
# is for. `payload` is the one that regresses first if the budget is retuned.
PROFILES = [
    ("tell me about Saibya", ["Saibya", "200 kilograms", "surveillance"]),
    ("tell me about ATM", ["Any Terrain Machine", "500 kilograms", "towing"]),
    ("tell me about NEXUS", ["Nano Exploration", "2 kilograms", "surveillance"]),
    ("explain Altius", ["climbing", "30 kilograms", "cleaning"]),
]

# High-scoring but unanswerable: one covered content word is enough to look
# confident against half a dozen unrelated sections at once. The robot should
# say it is unsure and offer the questions it *can* answer.
SHOULD_CLARIFY = [
    "battery",
    "surveillance",
    "what about safety",
    "does it have a camera",
    "the robot",
]

# Turns that are not questions. Running these through retrieval is how an
# assistant ends up answering "hi" with a battery specification.
SHOULD_CHAT = [
    ("hello", "greet"),
    ("hi", "greet"),
    ("good morning", "greet"),
    ("namaste", "greet"),
    # Thanks, including the padding people actually say it with. Matching only
    # the dictionary form sent "thank you very much" to the knowledge base.
    ("thanks", "thanks"),
    ("thank you", "thanks"),
    ("Thank you.", "thanks"),
    ("thank you very much", "thanks"),
    ("thanks a lot", "thanks"),
    ("ok thank you", "thanks"),
    ("thanks for the help", "thanks"),
    # Every way of saying "I'm finished" has to end the turn. A negative that
    # only acknowledges leaves the assistant asking "anything else?" forever.
    ("bye", "bye"),
    ("that's all", "bye"),
    ("no", "bye"),
    ("no thanks", "bye"),
    ("no thank you", "bye"),
    ("nothing else", "bye"),
    ("that's it", "bye"),
    ("i am done", "bye"),
    ("im good", "bye"),
    ("not now", "bye"),
    ("stop", "bye"),
    # Still here, nothing asked.
    ("ok", "ack"),
    ("nice", "ack"),
    ("yes", "ack"),
    ("got it", "ack"),
]

# The other half of small talk: turns that *contain* a greeting word but are
# real questions, and questions whose words overlap the small-talk lists. A
# module that can only ever intercept has to be shown what it must not touch.
CHAT_MUST_NOT_SWALLOW = [
    ("hi, what is NEXUS", "Nano Exploration"),
    ("hello, how much can Saibya carry", "200"),
    ("thanks, which industries use Altius", "maritime"),
    ("no line of sight range of ATM", "400"),
    ("what can you do", "Saibya"),
    ("what should I ask", "Saibya"),
    # "good" is an acknowledgement on its own and a plain adjective here
    ("is Saibya good for desert terrain", "Saibya"),
    # "stop" closes the conversation; "emergency stop" is a manual question
    ("what does the emergency stop do", "emergency"),
]

SHOULD_REFUSE = [
    "what is the capital of France",
    "tell me a joke",
    "what is the CEO's salary",
    "do you sell laptops",
    "what is the wifi password",
    "who is the CEO of Google",
    "give me the source code",
    "what is the profit margin",
    "how many units have you sold",
    # Micro was withdrawn from the range: the robot must hand this to a human
    # rather than answer from a stale catalogue page.
    "tell me about Micro",
]


# Facts only the synced copy of arnobot.in has (data/web/, app/sitesync.py).
# They must be answered, and from the website rather than company.md.
SHOULD_ANSWER_FROM_SITE = [
    ("who is Prijen Balar", "Duct Cleaning"),
    ("who is Harshil Shah", "Software & Website"),
    ("who is Noman Menon", "Hardware & Documentation"),
    ("what is iCreate ProtoQuik", "ProtoQuik"),
]

# The website copy is a fallback. With it loaded, these must still be
# answered from company.md, word for word as before.
CURATED_STAYS_CURATED = [
    ("who is the CEO", "Anmol Shah is the Founder and CEO"),
    ("how much can Saibya carry", "payload capacity of up to 200 kilograms"),
    ("are you hiring", "Yes, Arnobot is hiring"),
    ("which robot can climb walls", "Altius"),
]


CHECKS = 0


def _check(label: str, ok: bool, detail: str, failures: list) -> None:
    global CHECKS
    CHECKS += 1
    print(f"{'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        print(f"        {detail}")
        failures.append(label)


def main() -> int:
    build()
    conn = store.connect()
    retriever = Retriever(store.load_all(conn))
    conn.close()

    # respond(), not answer(): the small-talk router runs ahead of retrieval,
    # and a rule only the server applies is a rule these tests cannot catch
    # when it starts swallowing real questions.
    def ask(question):
        return respond(question, retriever)

    failures: list[str] = []
    print(
        f"threshold = {THRESHOLD}   clarify = {CLARIFY_THRESHOLD}   "
        f"chunks = {len(retriever.chunks)}\n"
    )

    print("-- should answer " + "-" * 52)
    for question, expected in SHOULD_ANSWER:
        result = ask(question)
        ok = result["answered"] and expected.lower() in result["answer"].lower()
        _check(
            f"{result['confidence']:.2f}  {question}",
            ok,
            f"want {expected!r}, got: {result['answer'][:110]}",
            failures,
        )

    print("\n-- product profiles carry the key data " + "-" * 30)
    for question, expected in PROFILES:
        result = ask(question)
        missing = [e for e in expected if e.lower() not in result["answer"].lower()]
        _check(
            f"{len(result['answer']):>3} chars  {question}",
            result["answered"] and not missing,
            f"missing {missing}: {result['answer'][:140]}",
            failures,
        )

    print("\n-- every reply offers somewhere to go next " + "-" * 26)
    for question, _ in SHOULD_ANSWER[:6] + PROFILES + [(q, "") for q in SHOULD_REFUSE[:3]]:
        result = ask(question)
        follow = result.get("followups") or []
        # Offering back the question just asked reads as not listening.
        repeats = [f for f in follow if f.rstrip("?").lower() == question.lower()]
        _check(
            f"{len(follow)} next  {question}",
            bool(follow) and not repeats,
            f"followups={follow}",
            failures,
        )

    print("\n-- product answers offer that product " + "-" * 31)
    for key, product in PRODUCTS.items():
        result = ask(f"tell me about {product['name']}")
        follow = result.get("followups") or []
        ok = bool(follow) and all(product["name"] in f for f in follow)
        _check(f"{product['name']} follow-ups", ok, f"got {follow}", failures)

    print("\n-- should ask me to clarify " + "-" * 41)
    for question in SHOULD_CLARIFY:
        result = ask(question)
        ok = result["mode"] == "clarify" and len(result.get("followups") or []) > 0
        _check(
            f"{result['confidence']:.2f}  {question}",
            ok,
            f"mode={result['mode']}: {result['answer'][:110]}",
            failures,
        )

    print("\n-- small talk is answered in kind " + "-" * 35)
    for question, kind in SHOULD_CHAT:
        result = ask(question)
        ok = result["mode"] == "chat" and result.get("kind") == kind
        _check(
            f"{kind:<7} {question}",
            ok,
            f"mode={result['mode']} kind={result.get('kind')}: {result['answer'][:90]}",
            failures,
        )

    print("\n-- ...and never swallows a real question " + "-" * 28)
    for question, expected in CHAT_MUST_NOT_SWALLOW:
        result = ask(question)
        ok = result["answered"] and expected.lower() in result["answer"].lower()
        _check(
            question,
            ok,
            f"mode={result['mode']}, want {expected!r}: {result['answer'][:110]}",
            failures,
        )

    print("\n-- should refuse and refer " + "-" * 42)
    for question in SHOULD_REFUSE:
        result = ask(question)
        # Must be a referral, not a clarification: there is no rewording of
        # "what is the CEO's salary" that this knowledge base can answer.
        ok = result["mode"] == "refer" and "contact the Arnobot team" in result["answer"]
        _check(
            f"{result['confidence']:.2f}  {question}",
            ok,
            f"mode={result['mode']}, leaked: {result['answer'][:110]}",
            failures,
        )

    print("\n-- company.md stays authoritative " + "-" * 35)
    for question, expected in CURATED_STAYS_CURATED:
        result = ask(question)
        ok = (
            result["answered"]
            and "origin" not in result
            and expected.lower() in result["answer"].lower()
        )
        _check(
            question,
            ok,
            f"origin={result.get('origin')}: {result['answer'][:110]}",
            failures,
        )

    print("\n-- website-only facts come from arnobot.in " + "-" * 26)
    if retriever.site is None:
        print("skip  no data/web/ copy yet — run `python -m app.sitesync`")
    else:
        for question, expected in SHOULD_ANSWER_FROM_SITE:
            result = ask(question)
            ok = (
                result["answered"]
                and result.get("origin") == "arnobot.in"
                and expected.lower() in result["answer"].lower()
            )
            _check(
                f"{result['confidence']:.2f}  {question}",
                ok,
                f"origin={result.get('origin')}, want {expected!r}: {result['answer'][:110]}",
                failures,
            )

    print(f"\n{CHECKS - len(failures)}/{CHECKS} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

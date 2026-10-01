# Arnobot Voice Assistant

An animated robot that answers questions about Arnobot Private Limited out
loud, running **entirely on your machine**. No OpenAI, no Pinecone, no cloud
LLM, no API keys. Ask a question by voice, the robot listens, thinks, and
speaks the answer — and if the answer isn't in its knowledge, it says so
instead of inventing one.

```
🎤 speak → text → hybrid search over company data → confident enough?
                                                    ├── yes    → speak the answer
                                                    ├── nearly → "did you mean…?"
                                                    └── no     → "contact the Arnobot team"
                                                          ↓
                                            …then suggest what to ask next
```

---

## Why this stack

The original plan was PostgreSQL + pgvector + Pinecone + OpenAI API. That is
the right architecture at scale, and the wrong one for a company FAQ. Sixty-odd
chunks fit in memory; a brute-force NumPy scan beats any index at that size,
and a vector database is a service to run, secure and pay for that buys you
nothing until you cross roughly 100k chunks.

| Layer | Choice | Why |
|---|---|---|
| Backend | **Python + FastAPI** | Async, typed, one file to run |
| UI | **Plain HTML/CSS/SVG** | No React, no build step, no `node_modules` |
| Animation | **CSS keyframes on inline SVG** | The whole robot is one `data-state` attribute |
| Speech in | **Web Speech API** → optional **faster-whisper** | Zero install; switch to Whisper for fully offline |
| Speech out | **Web Speech Synthesis** | Uses the Windows system voices — offline |
| Embeddings | **fastembed** (`bge-small-en-v1.5`, ONNX) | 130 MB, CPU, **no PyTorch**; downloads once then offline |
| Store | **SQLite** | One file, zero setup, ships with Python |
| Retrieval | **BM25 + dense vectors, fused (RRF)** | Keywords catch model names, vectors catch paraphrases |
| Answering | **Extractive** (+ optional local Ollama) | No generative model in the path ⇒ cannot hallucinate |
| Explaining | **Section plan per product** | Payload, features and use cases in one reply, still verbatim |

**The important one is the Answering row.** A RAG prompt that says "only use the
context" is a request, not a guarantee — the model can still drift. Here the
answer is assembled from sentences that literally exist in `data/company.md`.
There is nothing in the pipeline capable of inventing a spec, a founder, or a
customer.

---

## Quick start

```bash
bash run.sh        # macOS / Linux
```
```powershell
.\run.ps1          # Windows
```

Creates the venv, installs dependencies, indexes `data/`, and serves
<http://127.0.0.1:8000>. First run downloads the embedding model (~130 MB) and
the Whisper speech model (~75 MB), once.

Then click the mic and ask *"who is the CTO?"* or *"which robot can climb walls?"*

You can also deep-link a question: `http://127.0.0.1:8000/?q=what+is+NEXUS`

<details>
<summary>Manual steps</summary>

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.ingest
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```
</details>

---

## The robot

The character is one inline SVG: a humanoid bust with a pearl-white shell, a
dark glass visor with LED eyes and a seven-bar voice line, side sensor modules,
a slim graphite neck, an orbit ring around the head and a hover platform
beneath. No limbs and no cartoon colours — it has to hold up in a professional
demo. The shell colours are **fixed rather than themed**, so the robot looks
like itself in both light and dark mode.

Only the **light** changes: eyes, voice line, sensors, chest core, orbit,
platform and the answer card's edge all read from one `--glow` variable, so
each state is legible at a glance from across a room. Idle motion is slow and
eased — hovering, breathing, a blink and glance, a light sweep across the
visor, the orbit turning, motes rising.

| State | Colour | Motion |
|---|---|---|
| `idle` | Cyan | Hovers, blinks, glances, visor sheen, slow orbit, platform ripples |
| `listening` | Red | Sonar rings, eyes widen, head leans in, sensors pulse, faster orbit |
| `thinking` | Amber | Eyes narrow and sweep, scan line down the visor, spinner arc |
| `speaking` | Green | Voice line becomes an equaliser, chest core pulses |
| `clarifying` | Amber | Head tilts and **holds**, one eye narrows under a raised brow |
| `refusing` | Grey | Eyes dim and drop, apologetic brows, one slow head shake |

`clarifying` and `refusing` are deliberately different poses. A held tilt is a
question and invites another go; the shake is a full stop. Getting those the
right way round matters more than either animation. The squint matters too — a
lone raised brow over a wide-open eye reads as a stray mark, not an expression.

Every animation is driven by a single attribute — `stage.dataset.state` — so
any code path only has to call `setState()`, and the visuals cannot disagree
with the logic.

Inspect any pose without triggering it: `http://127.0.0.1:8000/#state=thinking`

Around the robot: the page enters in sequence on load, suggestions and product
cards cascade in, answers settle word by word, three dots show while it thinks,
and the send arrow becomes a **stop** button while it speaks — stopping it says
*"How can I help you?"* and hands the floor back.

`prefers-reduced-motion` disables every animation.

The screen shows **only what the robot says** — the match percentage, source
heading and index stats are gone, and the status line stays blank unless
something is actually broken.

## The layout

Full-screen and iOS-styled: a translucent nav bar with the Arnobot logo (the
two-tone mark on light, the white mark on dark), inset grouped question lists,
the answer on a card, product cards showing each robot's render, and a capsule
composer. Arnobot indigo is the one accent. The appearance control follows the
system (Auto) or pins Light or Dark, remembered per screen; the ⛶ button (or
**F**) hides the browser chrome for a kiosk.

```
┌───────────────────────────────────────────────────────────────┐
│ ARNOBOT logo     Interactive Robot    Online [Auto|☀|☾] Voice ⛶ │
├──────────────┬────────────────────────────────────────────────┤
│ ASK ME       │                 ╭────╮                         │
│  question  › │                 │ ●● │   robot                 │
│  question  › │                 ╰────╯                         │
│ MORE TOPICS  │      ┌──────────────────────────────┐          │
│  question  › │      │            ( what you asked )│          │
│              │      │ the answer                   │          │
│ ┌──────────┐ │      └──────────────────────────────┘          │
│ │ contact  │ │ [▣ Saibya][▣ ATM][▣ NEXUS][▣ Altius]           │
│ └──────────┘ │ (mic) ( 🔍 type a question            ↑ )      │
└──────────────┴────────────────────────────────────────────────┘
```

The rail carries **two groups**: the top one changes with every answer, so the
standing topics need a second group underneath that does not move.

The robot and the answer are centred **together as one block**. Letting the
stage take all the free space on its own strands the robot mid-column with the
text marooned at the bottom of the screen.

The robot gets a definite height, not a percentage: its container is sized by
its contents, so `height: 100%` is circular and resolves to nothing at all.
It then **shrinks to 180px when the answer runs past 360 characters** — a full
product profile needs the height more than the robot does, and without that the
centred block overflows and the robot slides up behind the header.

The answer is set left-aligned in a 64-character measure — a seven-line profile
set centred is a chore to read, however tidy it looks. When one still overflows,
the last line fades to show there is more; the check runs across two animation
frames, because measuring in one catches the previous layout and fades answers
that fit perfectly well.

Below 860px there is no side to put a rail on, so it moves beneath the robot and
the product cards drop to two columns.

### Beyond the answer

| Element | What it does |
|---|---|
| Header status | Reads `/api/health`; says "Connecting…" until it has actually connected, because claiming to be online before the first response is decoration |
| Product cards | The four platforms from `/api/products`, always on screen — the fastest route to what most people opened this to ask. Tapping one opens the showcase |

### Product showcase

A product card opens a full sheet over the page. On the left, the robot on a
360° turntable — drag to rotate, or it turns slowly on its own (Saibya, NEXUS
and Altius; ATM floats its render) — with field videos and photos beneath. On
the right, tabs for Overview, Specifications, Features, Applications and
Industries, with figures set in bold, while the robot speaks the overview.
It runs as a tour: the robot reads each tab in turn (Overview, Specifications,
Features, Attachments where there are any, Applications, Industries), then the
tabs keep cycling quietly; the media plays the turntable, each video to its end
and each photo for a few seconds, then loops. Tapping a tab or a thumbnail jumps
there and the tour carries on from it. "Hear the full brief" restarts the
narration; Stop silences it; Esc or ✕ closes.

Saibya has an **Attachments** tab: surveillance, gun mounting, payload carrying,
grass cutting and mine dispensing, each a card with its photo and the sentence
from its own `## Saibya … attachment` section in `company.md`.

The text comes from `/api/products/<key>`, which returns the product's five
sections **verbatim from `company.md`**, so the sheet and the spoken answer can
never disagree. Media lives in `web/assets/products/<key>/`: `360/frame-NN.webp`
(the website's turntable renders), `gallery-N.webp`, `video-N.mp4` with a
`video-N-poster.webp` still — all taken from the Arnobot website.

The product cards carry **no figures** on purpose. A card quoting a payload
could drift out of step with `data/company.md`; the answer behind the card is
where numbers belong.

### Suggestions, and what comes after an answer

Before the first question the rail is headed **Ask me** and holds six starters
covering the company, the range, picking a platform and buying. After every
reply it refills with **what to ask next**, and the heading changes with the
situation — *Ask me next* after an answer, *Did you mean* after a clarification.

The follow-ups are chosen by the backend, not the page (`followups` in the
`/api/ask` response), so a spoken answer and a tapped one behave identically.
Ask about NEXUS and you are offered its specifications, its use cases and its
industries; ask what the company makes and you are offered all four robots.
They are plain buttons calling the same `ask()` path as the mic.

The rail **dims while the robot is working, but never disappears**. It is a
fixture in the corner of your eye, and a list that vanishes on every question
is a list you stop looking at.

Note the greeting is displayed, not spoken — browsers block speech synthesis
until the user interacts with the page, so a spoken greeting on load would be
silently dropped. Only the answer is ever spoken; the suggestions are on screen
to be tapped.

---

## The knowledge base

`data/company.md` is built from Arnobot's public-facing material: the company
brief, catalogue, pitch deck, the Altius/Saibya/NEXUS brochures and spec
sheets, the ATM check sheet, and the Saibya and NEXUS manuals. It covers the
company, the three founders, awards, pilots, clients, and the operating,
safety, charging and troubleshooting procedures for Saibya and NEXUS.

Each of the four platforms — **Saibya, ATM, NEXUS, Altius** — carries the same
five sections, and the answerer relies on that shape:

| Section | Answers |
|---|---|
| `<name> overview` | what it is |
| `<name> specifications` | size, weight, **payload**, battery, drive |
| `<name> features` | what it can do, ranges, ratings, runtime |
| `<name> use cases` | what it is used for |
| `<name> industries` | which sectors it suits, where it has been deployed |

Add a fifth robot by writing those five headings and adding it to `PRODUCTS` in
`app/products.py`; profiles, facet routing and follow-ups all come from that
one entry. The ATM sections are the fullest, because the `CheckSheet_ATM`
spec sheet carries IP rating, runtime, charge time, remote ranges, tyre size,
body material and steering that the catalogue page never mentioned.

It also answers the business questions the source documents never address —
pricing, buying, demos, export, careers — with an honest pointer to the company
contact rather than a refusal or an invented fact.

**Deliberately excluded as confidential**: the NDA, offer and acceptance
letters, the purchase agreement, the handover agreement, warranty drafts, the
vendor BOM, the funding ask and cost structure from the pitch deck, the EOS
weapon-station tender specification, and the private mobile number of the
support contact named in the NEXUS manual. None of it is in the index.

To change what the robot knows, edit `data/company.md` and restart. The server
compares the newest file mtime in `data/` against the index timestamp and
rebuilds itself when it is behind, so a stale index is not a state you can end
up in. Drop in more `.md`, `.txt` or `.json` files alongside it and they are
picked up the same way. `POST /api/reindex` still rebuilds without a restart.

### The `also:` line matters more than anything else here

It is the single highest-leverage thing in the data file. A small embedding
model has a limited vocabulary: if your text says *"located in Ahmedabad"* and
the user asks *"which city are you based in"*, the words **city** and **based**
appear nowhere, and confidence lands at 0.15 — a refusal. Add
`also: which city, where are you based, address` and the same question scores
0.89.

Write the `also:` line as the phrasings **real users say**, not synonyms of
your headings. It is indexed and embedded, but never read back in the answer.

```markdown

### Synced from arnobot.in

`data/web/arnobot_in.md` is a copy of the public pages of <https://arnobot.in>,
generated by `app/sitesync.py` (standard library only). The server re-checks
the site in the background every hour and refetches once the copy is a day old
(`ROBOT_SITE_MAX_AGE_HOURS`); `POST /api/sync` or `python -m app.sitesync
--force` does it now. A failed fetch keeps the last good copy.

`company.md` stays authoritative. The website text has its own index and is
only consulted when `company.md` would refer the visitor or ask them to
rephrase, and then it must clear a stricter bar (`ROBOT_SITE_THRESHOLD`, 0.50).
Answers are still verbatim sentences from the site — nothing is generated.
Set `ROBOT_SITE_SYNC=off` to stop syncing.

## Altius overview
also: what is altius, climbing robot, wall climbing, vertical robot
Altius is Arnobot's vertical climbing robot, built to access vertical and
hard-to-reach structures.
```

---

## How answering works

1. **Retrieve** — BM25 and vector search run in parallel, fused with Reciprocal
   Rank Fusion. RRF is used to *shortlist* only; its scores are rank-based and
   not comparable between questions, so they must never be a threshold.
2. **Score** — a separately calibrated confidence in `0..1`:

   ```
   confidence = (0.85 × strongest signal + 0.15 × weaker signal) × grounding
   ```

   *Semantic* is the cosine rescaled from the band the model actually uses
   (0.50 → 0.78 for bge-small; unrelated text sits near 0.45, so raw cosine is
   squeezed and misleading). *Keyword* is the share of the question's content
   words present in the chunk, weighted by rarity.

   Taking the **strongest** signal rather than a weighted sum is deliberate: a
   pure paraphrase that shares no keywords would otherwise be capped below the
   threshold and refused.

   The cosine is computed for **every** shortlisted candidate, not just the
   ones the dense retriever ranked. Reusing only the dense top-K let a
   keyword-only hit fall through to coverage alone and score a perfect 1.0
   while the embedder had ranked it nowhere — which is exactly how *"what is
   your product range"* once returned the Micro spec sheet.
3. **Ground** — scale down by any question words absent from the *entire*
   corpus. This is the one that stops the classic RAG failure: *"how much does
   Saibya cost"* matches the Saibya chunk at 0.75 because the **topic** is
   right, and would happily answer with its dimensions. But `salary`, `price`,
   `Google` and `profit` occur nowhere in the knowledge base, which is decisive
   evidence the answer isn't there. Matching the right topic is not the same as
   having the requested fact.
4. **Gate** — three outcomes, and the order is fixed. Above
   `ROBOT_THRESHOLD` (default `0.42`) it may answer. Between that and
   `ROBOT_CLARIFY_THRESHOLD` (`0.22`) it **asks**. Below, it **refers** you to
   the team. It never guesses.
5. **Extract** — from the winning chunk, pick the sentences that overlap the
   question, capped at 3 sentences / 420 characters so it is short enough to speak.

```powershell
.\.venv\Scripts\python.exe test_answers.py    # 131/131 passed
```

Tune thresholds by running the suite, not by intuition.

### The three replies

**Answer** is the ordinary path. **Refer** replaces the old dead-end refusal:
the guarantee is unchanged — the robot still states no fact it cannot ground —
but it now names who can help instead of stopping. Refusing a customer is a
product decision; refusing them *and* leaving them nowhere to go is just bad
manners.

**Clarify** is the new one, and it exists because confidence alone is a bad
detector for a certain kind of failure. Ask a one-word question — *"battery"* —
and it scores **0.90**: its single content word is covered perfectly by every
section that mentions a battery. High confidence, completely unanswerable.
So a high score is only trusted when it is high for the right reason. The robot
clarifies when all three hold:

- **no product is named** — "NEXUS battery" has one subject however many NEXUS
  sections tie for it;
- **the question carries one content word or fewer**, ignoring question words —
  "which city are you based in" has enough to pin a subject, "battery" does not;
- **the tied sections disagree about their subject** — four NEXUS sections
  scoring alike is a well-understood question, not a confused one.

It then offers back the closest questions it *can* answer, drawn from the very
candidates that tied. A near miss on the low side clarifies too, but only when
every word is one the corpus uses: no rewording of *"what is Google's revenue"*
will ever make it answerable here, so that is a referral, not a rephrase.

### The turns that are not questions

"Hello" run through hybrid retrieval produces a confident-looking match against
whatever section shares a stopword with it — which is how an assistant ends up
answering a greeting with a battery specification. `app/smalltalk.py` catches
those turns ahead of retrieval and answers them in kind:

| Turn | Reply |
|---|---|
| hello, hi, good morning, namaste | Introduces itself and says what it covers |
| thanks, thank you, cheers | "You are welcome. Is there anything else…" |
| ok, nice, yes, got it | "What else would you like to know?" |
| **no, no thanks, nothing else, that's it, i'm done, bye, stop** | Thanks them and closes, with the team's contact |

**A negative has to close the conversation.** This is the rule that earns its
keep. The reply to "thanks" asks whether there is anything else; if "no" is
only an acknowledgement, the assistant answers it with *another* question and
the two of you are stuck in a loop with no exit. The farewell asks nothing —
a goodbye that ends in a question does not end.

**Politeness padding is stripped before matching.** People say "ok thank you"
and "thank you very much", not the dictionary form. Matching the whole string
alone sent both of those to the knowledge base, which had never heard of them,
and answered a thank-you with a referral.

The matching stays strict about scope: a phrase counts only as the **whole**
turn, or as a greeting sitting in front of a real question. "Hi" must never
fire on "which robot climbs walls", "no" must never fire on "no line of sight
range of ATM", and "stop" must not eat "what does the emergency stop do" — all
three are in the suite. A greeting *before* a question is stripped and the
question answered, so "hi, how much can ATM carry" gets the payload, not a
hello.

`respond()` is the single entry point — small talk, then retrieval, then the
gate — so the route and the test suite exercise the same path. A small-talk
rule that only the server applies is a rule the tests cannot catch when it
starts swallowing real questions.

### Saying thank you

Off by default — said after every answer it reads as filler. Set
`ROBOT_CLOSING` to a line to turn it on: after an answer, if the room goes quiet
for `ROBOT_CLOSING_DELAY_MS` (25s), the robot says it and re-opens the floor. Once per answer, never while
it is still speaking, and never to a tab nobody is looking at.

It deliberately does **not** fire after a clarification: that is a question *to*
the visitor, and thanking them while waiting on their reply is talking past
them. Small talk does not trigger it either — those replies already re-open the
floor in their own words.

The line is served from `/api/health`, not hardcoded in the page, so every
sentence the robot says stays configurable by environment variable in one file.

### When the author already wrote the question down

The `also:` line is now stored verbatim alongside each chunk, and an exact
match against it **promotes that section to the front of the results**.

This matters for questions that are one word long after stopwords. "What can
you do" scores **0.88 against the section written for it and 0.88 against
Saibya's do-not list** — a genuine tie, decided by list order. A phrasing the
author wrote down beats a coin toss. It also exempts the question from the
ambiguity check below: thin by every other measure, but with one right answer.

Promotion reorders only. The confidence gate still runs, so an authored phrase
that cannot clear the threshold shows up as a data problem rather than being
waved through.

### Explaining a product

Retrieval answers the question asked. A person explaining a machine also
decides *what else* you need to hear. Ask *"tell me about ATM"* and the reply is
stitched from that product's own sections — what it is, its size and **payload**,
a key feature, what it is **used for** — about 700 characters, or 45 seconds of
speech. Every sentence is still literally from `data/company.md`; `app/products.py`
only chooses which sections to read and in what order.

Two rules keep that from misfiring:

- **A product profile only replaces retrieval when retrieval landed on that
  product's own pages.** *"How much does Saibya cost"* is a pricing question
  that happens to name a robot, and answering it with the robot's dimensions is
  exactly the failure this guards against.
- **When the facet cue and retrieval disagree, the text decides.** *"What tyres
  does ATM use"* reads like a use-case question and is a specification one —
  only the specifications say "tyres", so that section wins. Ties go to
  retrieval; the keyword list only wins when it can show the words.

### What the suite checks

`SHOULD_ANSWER` is the smallest of the six lists, because the interesting
failures are everywhere else:

| List | Checks |
|---|---|
| `SHOULD_ANSWER` | the fact is stated, and pricing survives naming a robot |
| `PROFILES` | each product's explanation carries payload **and** use cases |
| follow-ups | every reply offers a next step, and never re-offers the question just asked |
| product follow-ups | a NEXUS answer offers NEXUS questions, not generic ones |
| `SHOULD_CLARIFY` | thin questions are admitted as thin |
| `SHOULD_CHAT` | greetings, thanks and goodbyes answer in kind |
| `CHAT_MUST_NOT_SWALLOW` | …and never eat a real question that shares their words |
| `SHOULD_REFUSE` | mode is `refer`, **not** `clarify` |

That last distinction is the one to keep honest. Asserting "did not answer"
would let a refusal pass by offering to rephrase, and there is no rewording of
*"what is the CEO's salary"* that this knowledge base can answer. The refusal
list covers pricing, salaries, revenue figures, unit counts, other companies —
and Micro, the withdrawn platform.

### A note on pricing questions

*"How much does Saibya cost"* is deliberately **answered**, not refused — with
"Arnobot does not publish prices… contact us for a quotation". Refusing a
question every real customer asks is worse product behaviour than answering it
honestly. The grounding check still blocks anything that would require a figure
the data doesn't have.

---

## Configuration

Every setting is an environment variable; nothing needs a code change.

| Variable | Default | Effect |
|---|---|---|
| `ROBOT_THRESHOLD` | `0.42` | Raise to refuse more, lower to answer more |
| `ROBOT_CLARIFY_THRESHOLD` | `0.22` | Floor of the "ask, don't answer" band |
| `ROBOT_CLARIFY_MAX_OOV` | `0.20` | Unknown-word share above which a near miss is a referral, not a rephrase |
| `ROBOT_AMBIGUITY_MARGIN` | `0.06` | How close a rival section must score to count as a tie |
| `ROBOT_PROFILE_MAX_CHARS` | `820` | Length budget for a full product explanation |
| `ROBOT_CONTACT` | *phone + email* | Where referrals are sent |
| `ROBOT_TOP_K` | `5` | Chunks shortlisted per question |
| `ROBOT_STRONG_WEIGHT` | `0.85` | Lower it to require both signals to agree |
| `ROBOT_OOV_PENALTY` | `0.85` | How hard to punish unknown question words; `0` disables |
| `ROBOT_EMBEDDINGS` | `on` | `off` = keyword-only, zero download |
| `ROBOT_FALLBACK` | *"…contact the Arnobot team…"* | The referral wording |
| `ROBOT_CLARIFY_PREFIX` | *"I am not sure I understood…"* | The clarification opener |
| `ROBOT_GREETING` | *"Hello. I am Arnobot's assistant…"* | Reply to hello |
| `ROBOT_THANKS` | *"You are welcome…"* | Reply to thanks |
| `ROBOT_FAREWELL` | *"Thank you for your time…"* | Reply to bye or a declined offer |
| `ROBOT_ACK` | *"What else would you like to know?"* | Reply to "ok" / "nice" |
| `ROBOT_CLOSING` | *(empty — off)* | Optional line spoken when the room goes quiet |
| `ROBOT_SITE_SYNC` | `on` | Keep `data/web/` synced with arnobot.in |
| `ROBOT_SITE_MAX_AGE_HOURS` | `24` | How old the website copy may get |
| `ROBOT_SITE_THRESHOLD` | `0.50` | Confidence a website answer needs |
| `ROBOT_WHISPER_PROMPT` | Arnobot's product names | Words the speech recogniser should expect |
| `ROBOT_CLOSING_DELAY_MS` | `25000` | How long the quiet has to last first |
| `ROBOT_WHISPER` | `auto` | `auto` = on if faster-whisper is installed; `on` / `off` |
| `ROBOT_CONTACT_PHONE` / `_EMAIL` / `_WEB` | Arnobot's | Contact card and spoken referral |
| `ROBOT_OLLAMA` | `off` | `on` = rephrase answers with a local model |

---

## Runs without internet

After the first start (which downloads the embedding model and the Whisper
speech model, ~200 MB together), the assistant needs no network at all:

| Part | Offline |
|---|---|
| Answers, search, product showcase, images, videos | Local files and a local index |
| Speech out | The OS voices (Karen by default) |
| Speech in | Whisper on this machine; Chrome/Edge fall back to it when their online recogniser fails |
| Models | `app/config.py` sets `HF_HUB_OFFLINE` once both caches exist, so nothing checks the hub on start (`ROBOT_ONLINE_MODELS=on` to allow it) |
| arnobot.in sync | Fails quietly and keeps the last copy; resumes when the network returns |

Verified by starting a second server with every outbound request sent to a
dead proxy: it started, answered, transcribed speech, and the site sync
reported `failed` in under a second without touching the existing copy.

## Fully offline speech input

The mic uses the browser's built-in recogniser where it works, because it
transcribes live as you speak. **Chrome and Edge send that audio to
Google/Microsoft**, and **Brave blocks that service entirely** (it fails with a
`network` error). So whenever faster-whisper is installed (it is in
`requirements.txt`), the page records instead and posts the clip to `/api/stt`,
transcribed locally by Whisper `tiny.en` (~75 MB, int8 CPU) — automatically in
Brave and Firefox, and in Chrome/Edge the moment their online service fails.
Nothing leaves the machine. The turn ends after a 2.5 s pause, 9 s of no
speech, or 30 s; tapping the mic again sends at once.

The voice is the OS's: Karen (Apple) by default at 0.95 speed, falling back
through other female voices; `?voice=Name` overrides it.

## Optional: local phrasing model

Extractive answers read like the source text because they *are* the source
text. For more conversational phrasing, install [Ollama](https://ollama.com):

```powershell
ollama pull qwen2.5:1.5b-instruct
$env:ROBOT_OLLAMA = "on"
```

It only rewrites retrieved context and runs after the threshold check, so
refusals stay refusals. Still fully local — but it reintroduces a generative
model, and with it a small chance of drift. Off by default for that reason.

---

## Project layout

```
app/
  config.py     all settings, env-overridable
  text.py       chunking, tokenising, alias parsing
  embedder.py   local ONNX embeddings, degrades to keyword-only
  store.py      SQLite schema + vector blobs
  retriever.py  BM25 + dense + RRF + calibrated confidence + grounding
  products.py   which robot, which facet, what to suggest next
  smalltalk.py  greetings, thanks, goodbyes — the turns that are not questions
  answerer.py   respond(): small talk -> retrieval -> gate -> profile
  ingest.py     data/ -> index
  sitesync.py   arnobot.in -> data/web/arnobot_in.md
  main.py       FastAPI routes
web/            animated SVG robot UI (no build step), favicon, product renders
run.sh          macOS / Linux launcher (run.ps1 on Windows)
data/           company.md — the knowledge base
test_answers.py accuracy + refusal suite
```

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/ask` | `{"question": "..."}` → answer, `mode` (`answer`/`clarify`/`refer`), confidence, `followups`, sources |
| `GET /api/products` | The four platforms for the product cards — name, category, the question each card asks |
| `POST /api/reindex` | Rebuild the index from `data/` |
| `GET /api/health` | Chunk count, embedder, threshold |
| `POST /api/stt` | Offline transcription (when enabled) |
| `GET /api/docs` | Swagger UI |

## Known data issues

Two conflicts in the source documents. In both, the catalogue figure is indexed
and the conflicting one omitted, so the robot never states both — but the
documents themselves are still wrong somewhere and are worth reconciling.

| Field | Catalogue | Other document | Indexed |
|---|---|---|---|
| Saibya battery / clearance / payload | 24 V 50 Ah, 135 mm, 200 kg | Getting-started manual: 24 V 110 Ah, 180 mm, 25 kg limit | Catalogue |
| ATM payload | Up to 500 kg | Spec sheet `APL/SPC/ATM/Rev_01`: 100 kg | Catalogue |

The ATM one is the sharper of the two: a fivefold difference between the
marketing catalogue and the revision-controlled engineering sheet is the kind
of thing that turns into a warranty argument.

Micro is **not** in the index. It appears in the catalogue as a fifth platform
but has been withdrawn from the range, so questions about it are referred to
the team rather than answered from a stale page.

## When to outgrow this

Move to pgvector or Qdrant past **~100k chunks** or if you need multi-tenant
filtering. Swap the extractive answerer for a generative one when questions
need *synthesis across* several documents rather than a lookup. Until then, the
extra infrastructure costs latency and money and buys no accuracy.

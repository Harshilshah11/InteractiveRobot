"""Keep a copy of arnobot.in in the knowledge base.

Fetches the public pages of the company website, keeps only their readable
content (no menus, footers, pop-ups, forms or buttons), and writes it to
data/web/arnobot_in.md in the same `## heading` / `also:` / sentences format
as data/company.md. The ingester then indexes it like any other file, and the
answerer reads from it only when company.md has no confident answer — the
curated file stays authoritative, and every reply is still a sentence that
literally exists on the website.

Run:  python -m app.sitesync            (refetch if older than a day)
      python -m app.sitesync --force    (refetch now)

Pure stdlib: urllib for fetching, html.parser for reading.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from .config import DATA_DIR, DB_PATH

SITE = os.getenv("ROBOT_SITE_URL", "https://arnobot.in").rstrip("/")
OUT_FILE = DATA_DIR / "web" / "arnobot_in.md"
# When the site was last checked lives outside data/, so an unchanged site
# does not bump the knowledge file's mtime and force a needless reindex.
STATE_FILE = DB_PATH.parent / "sitesync.json"

MAX_PAGES = int(os.getenv("ROBOT_SITE_MAX_PAGES", "40"))
TIMEOUT = float(os.getenv("ROBOT_SITE_TIMEOUT", "20"))
USER_AGENT = "Mozilla/5.0 (compatible; ArnobotAssistantSync/1.0; +https://arnobot.in)"

# Pages with nothing an assistant should read out.
SKIP_PATH = re.compile(r"privacy|terms|cookie|login|admin|/_next|/api/", re.I)
SKIP_EXT = re.compile(r"\.(?:png|jpe?g|webp|gif|svg|ico|css|js|pdf|mp4|webm|zip|xml|json)$", re.I)

# Whole subtrees that are page furniture, never content.
SKIP_TAGS = {
    "script", "style", "noscript", "svg", "template", "iframe", "head",
    "header", "nav", "footer", "form", "button", "select", "textarea",
    "label", "video", "audio", "dialog", "canvas", "picture",
}
# Class-name parts that mark furniture: pop-ups, menus, call-to-action bands.
SKIP_CLASS_PARTS = {
    "modal", "menu", "submenu", "overlay", "sheet", "cta", "dropdown",
    "loader", "loading", "cookie", "toast", "backdrop", "drawer", "popup",
    "breadcrumb", "skip",
}
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}
BLOCK_TAGS = {
    "p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "div", "section",
    "article", "main", "aside", "td", "th", "dt", "dd", "tr", "ul", "ol",
    "blockquote", "figcaption", "br",
}
INLINE_TAGS = {"span", "strong", "b", "em", "i", "a", "small", "code", "time", "abbr", "sup", "sub"}
# An inline element styled as a label reads as "Label: value" with the next one.
LABEL_CLASS = re.compile(r"label|name|key|term", re.I)
# Calls to action that survive the class filter as plain text.
CTA_TEXT = re.compile(
    r"\b(apply now|schedule a (?:live |field )?demo|request (?:a )?brochure|learn more|"
    r"read more|view all|see all|send a message|get started|book a demo)\b",
    re.I,
)
HEADINGS = {"h1": 1, "h2": 2, "h3": 3}


# --------------------------------------------------------------------------
# HTML -> blocks
# --------------------------------------------------------------------------
def _is_furniture(tag: str, attrs: dict) -> bool:
    if tag in SKIP_TAGS:
        return True
    # Not the `hidden` attribute: Next.js streams real page content inside
    # <div hidden id="S:0"> and swaps it in with a script after load.
    if attrs.get("aria-hidden") == "true":
        return True
    if attrs.get("role") in {"dialog", "navigation", "banner", "contentinfo"}:
        return True
    # A link styled as a button is a call to action, not content.
    classes = (attrs.get("class") or "").split()
    if tag == "a" and any(c.startswith("btn") for c in classes):
        return True
    for cls in classes:
        for part in re.split(r"[-_]+", cls):
            part = part.lower()
            if part in SKIP_CLASS_PARTS or (len(part) > 3 and part.endswith("cta")):
                return True
    return False


class _Reader(HTMLParser):
    """Turns a page into an ordered list of (kind, text) blocks.

    kind is "h1".."h3" for headings, "item" for list entries and card titles,
    and "para" for running text. Everything inside furniture is dropped.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        # (tag, skipping, uid, class) for every open element
        self.stack: list[tuple[str, bool, int, str]] = []
        # (kind, text, container uid) — the container decides eyebrows
        self.blocks: list[tuple[str, str, int]] = []
        self.buf: list[str] = []
        self._uid = 0
        self._sep = ""  # separator owed before the next run of text
        self.title = ""
        self._in_title = False
        self.links: list[str] = []

    # -- helpers --------------------------------------------------------
    def _skipping(self) -> bool:
        return bool(self.stack) and self.stack[-1][1]

    def _container(self) -> int:
        for tag, _, uid, _ in reversed(self.stack):
            if tag not in HEADINGS and tag not in INLINE_TAGS:
                return uid
        return 0

    def _kind(self) -> str:
        for tag, *_ in reversed(self.stack):
            if tag in HEADINGS:
                return tag
            if tag in {"li", "h4", "h5", "h6", "dt", "dd", "td", "th"}:
                return "item"
        return "para"

    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        self.buf = []
        self._sep = ""
        if text:
            self.blocks.append((self._kind(), text, self._container()))

    # -- parser callbacks -----------------------------------------------
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self._in_title = True
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag in BLOCK_TAGS:
            self._flush()
        if tag in VOID_TAGS:
            return
        if tag in INLINE_TAGS and not self._sep:
            self._sep = " "
        skip = self._skipping() or _is_furniture(tag, attrs)
        self._uid += 1
        self.stack.append((tag, skip, self._uid, attrs.get("class") or ""))

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self.buf.append(" ")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in VOID_TAGS:
            return
        if tag in BLOCK_TAGS:
            self._flush()
        # Pop to the matching open tag; tolerate sloppy nesting.
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                closing = self.stack[i]
                del self.stack[i:]
                if tag in INLINE_TAGS and not closing[1]:
                    # <span>Phone</span><a>+91…</a> -> "Phone: +91…";
                    # <strong>200 kg</strong>payload -> "200 kg payload".
                    self._sep = ": " if LABEL_CLASS.search(closing[3]) else " "
                break

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if self._skipping():
            return
        if self._sep and data.strip():
            if self.buf and not "".join(self.buf).endswith((" ", "\n")) and not data[:1].isspace():
                self.buf.append(self._sep)
            elif self._sep == ": " and self.buf:
                self.buf.append(": ")
            self._sep = ""
        self.buf.append(data)

    def close(self):
        super().close()
        self._flush()


# --------------------------------------------------------------------------
# blocks -> sections of speakable sentences
# --------------------------------------------------------------------------
def _clean(text: str) -> str:
    text = unescape(text)
    text = text.replace("\u00a0", " ").replace("\u00ad", "")  # nbsp, soft hyphen
    text = re.sub(r"[→↗↓›»]+", " ", text)
    text = re.sub(r"\s+:\s*", ": ", text)
    text = re.sub(r"\s+([,.;!?])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip(" -–—|•")


def _sentence(text: str) -> str:
    text = _clean(text)
    if text and text[-1] not in ".!?":
        text += "."
    return text[:1].upper() + text[1:] if text else text


def _page_subject(title: str) -> str:
    """"NEXUS (Compact Tactical Robot) | ARNOBOT" -> "NEXUS (Compact Tactical Robot)"."""
    subject = re.split(r"\s+[|–—-]\s+", _clean(title))[0].strip()
    return subject if subject and subject.upper() != "ARNOBOT" else "Arnobot"


def _words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9]+", text))


def _short(subject: str) -> str:
    """"NEXUS (Compact Tactical Robot)" -> "NEXUS"."""
    return re.sub(r"\s*\(.*?\)", "", subject).strip() or subject


def _strip_cta(text: str) -> str:
    """Drop short call-to-action sentences ("Apply Now.") from a block."""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)
    kept = [p for p in parts if not (CTA_TEXT.search(p) and _words(p) <= 6)]
    return " ".join(kept).strip()


def _is_marker(text: str) -> bool:
    """Step numbers and shouted one-word labels: "01", "BUILT", "SAFE"."""
    return len(text) <= 12 and not re.search(r"[a-z]", text)


def _sections(
    blocks: list[tuple[str, str, int]], subject: str, product: bool
) -> list[tuple[str, list[str]]]:
    """Group blocks under their heading and turn each group into sentences.

    Running text is kept as written. Short list entries ("200 kg payload
    capacity") are not sentences on their own, so a run of them becomes one,
    led by what they are a list of: "NEXUS features: 3 kg ultra-lightweight
    platform; Fully invertible ...".
    """
    # A short block sharing its container with the heading that follows is
    # that heading's eyebrow ("Hardware & Firmware" above "Robotics Engineer"),
    # not the tail of the section before.
    ordered: list[tuple[str, str]] = []
    for n, (kind, text, box) in enumerate(blocks):
        nxt = blocks[n + 1] if n + 1 < len(blocks) else None
        if (
            kind not in HEADINGS
            and nxt
            and nxt[0] in HEADINGS
            and nxt[2] == box
            and _words(text) <= 6
        ):
            ordered.append((nxt[0], nxt[1]))
            ordered.append(("item" if kind == "item" else "eyebrow", text))
            blocks[n + 1] = ("skip", "", box)
            continue
        if kind != "skip":
            ordered.append((kind, text))

    out: list[tuple[str, list[str]]] = []
    short = _short(subject)
    heading = ""
    paras: list[str] = []
    items: list[str] = []

    def lead() -> str:
        if not product:
            return heading
        if not heading or short.lower() in heading.lower():
            return short
        return f"{short} {heading.lower()}"

    def flush_items():
        nonlocal items
        if items:
            label = lead()
            for start in range(0, len(items), 6):
                listed = "; ".join(_clean(i).rstrip(".") for i in items[start : start + 6])
                paras.append(_sentence(f"{label}: {listed}" if label else listed))
        items = []

    def flush_section():
        nonlocal paras
        flush_items()
        if paras:
            out.append((heading, paras))
        paras = []

    just_headed = False
    for kind, text in ordered:
        text = _strip_cta(_clean(text))
        if not text:
            continue
        if kind in HEADINGS:
            flush_section()
            # a rhetorical heading names no topic; its text still counts
            heading = "" if text.endswith("?") else text.rstrip(".!")
            just_headed = True
            continue
        subtitle = just_headed and kind == "para" and _words(text) <= 6 and not re.search(r"\d", text)
        just_headed = False
        if _is_marker(text) or subtitle:
            continue  # "01", "BUILT"; "What the machine does" under "Features"
        if kind == "eyebrow":
            continue  # a tagline above a heading: decoration, not a fact
        if kind == "item":
            # A long, punctuated entry is already a sentence.
            if _words(text) >= 10 and text[-1] in ".!?":
                flush_items()
                paras.append(_sentence(text))
            else:
                items.append(text)
            continue
        flush_items()
        if _words(text) < 4:
            continue  # stray labels and fragments
        paras.append(_sentence(text))
    flush_section()
    return out


def _also(subject: str, heading: str) -> str:
    """Phrasings to match on: the heading, and the heading with the subject."""
    short = _short(subject)
    candidates = [heading, f"{short} {heading}", f"{subject} {heading}"] if heading else [short, subject]
    phrases: list[str] = []
    for phrase in candidates:
        phrase = re.sub(r"[^A-Za-z0-9 ]+", " ", phrase).strip().lower()
        phrase = re.sub(r"\s+", " ", phrase)
        if phrase and phrase not in phrases:
            phrases.append(phrase)
    return ", ".join(phrases)


# --------------------------------------------------------------------------
# fetching
# --------------------------------------------------------------------------
def _fetch(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            if resp.status != 200 or "html" not in resp.headers.get("Content-Type", ""):
                return None
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def _robots_disallows() -> list[str]:
    """Disallow rules for all agents. A missing robots.txt allows everything."""
    req = urllib.request.Request(f"{SITE}/robots.txt", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            if resp.status != 200 or "text/plain" not in resp.headers.get("Content-Type", ""):
                return []
            body = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return []
    rules, applies = [], False
    for line in body.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (s.strip() for s in line.split(":", 1))
        if key.lower() == "user-agent":
            applies = value == "*"
        elif key.lower() == "disallow" and applies and value:
            rules.append(value)
    return rules


def _normalise(href: str, base: str) -> str | None:
    url = urllib.parse.urljoin(base, href.split("#", 1)[0])
    parts = urllib.parse.urlsplit(url)
    site = urllib.parse.urlsplit(SITE)
    if parts.scheme not in {"http", "https"} or parts.netloc != site.netloc:
        return None
    path = parts.path.rstrip("/") or "/"
    if SKIP_PATH.search(path) or SKIP_EXT.search(path):
        return None
    query = f"?{parts.query}" if parts.query else ""
    return f"{SITE}{path}{query}"


def _sitemap_urls() -> list[str]:
    xml = _fetch_text(f"{SITE}/sitemap.xml")
    if not xml or "<urlset" not in xml:
        return []
    return [u for u in (_normalise(m, SITE) for m in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", xml)) if u]


def _fetch_text(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="replace") if resp.status == 200 else None
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def crawl() -> tuple[list[dict], list[str]]:
    """Fetch and read every page. Returns (pages, errors)."""
    disallow = _robots_disallows()
    allowed = lambda url: not any(  # noqa: E731
        urllib.parse.urlsplit(url).path.startswith(rule) for rule in disallow
    )

    queue = [f"{SITE}/"] + _sitemap_urls()
    seen: set[str] = set()
    pages, errors, digests = [], [], set()
    while queue and len(seen) < MAX_PAGES:
        url = queue.pop(0)
        if url in seen or not allowed(url):
            continue
        seen.add(url)
        html = _fetch(url)
        if html is None:
            errors.append(url)
            continue
        reader = _Reader()
        reader.feed(html)
        reader.close()
        # The same page under two URLs ("/product" and "/product?id=saibya")
        # would only double every answer's weight.
        digest = hash(tuple(reader.blocks))
        if digest in digests:
            continue
        digests.add(digest)
        if "not found" in reader.title.lower():
            continue
        pages.append({"url": url, "title": reader.title, "blocks": reader.blocks})
        for href in reader.links:
            nxt = _normalise(href, url)
            if nxt and nxt not in seen and nxt not in queue:
                queue.append(nxt)
    return pages, errors


# --------------------------------------------------------------------------
# pages -> markdown
# --------------------------------------------------------------------------
def render(pages: list[dict]) -> tuple[str, dict]:
    # Text that repeats across most pages is furniture the class filter
    # missed — a tagline, a loading notice, the same call to action.
    counts = Counter(text for page in pages for text in {b[1] for b in page["blocks"]})
    common = {t for t, n in counts.items() if len(pages) >= 3 and n >= max(3, len(pages) // 2)}

    body: list[str] = []
    seen_sentences: set[str] = set()
    n_sections = n_sentences = 0
    for page in pages:
        subject = _page_subject(page["title"])
        blocks = [b for b in page["blocks"] if b[1] not in common]
        product = "/product" in page["url"]
        for heading, paras in _sections(blocks, subject, product):
            fresh = []
            for sentence in paras:
                key = sentence.lower()
                if key in seen_sentences or _words(sentence) < 3:
                    continue
                seen_sentences.add(key)
                fresh.append(sentence)
            if not fresh:
                continue
            same = not heading or heading.lower() in {subject.lower(), _short(subject).lower()}
            title = subject if same else f"{subject} — {heading}"
            body += [f"## {title}", f"also: {_also(subject, '' if same else heading)}", *fresh, ""]
            n_sections += 1
            n_sentences += len(fresh)

    sources = "\n".join(f"     {p['url']}" for p in pages)
    header = (
        "<!--\n"
        "  GENERATED by app/sitesync.py from the public pages of "
        f"{SITE} — do not edit;\n"
        "  it is rewritten on the next sync. Curated facts belong in company.md,\n"
        "  which always takes priority over this file.\n"
        f"  Synced: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
        f"  Sources:\n{sources}\n"
        "-->\n\n"
        "# arnobot.in\n\n"
    )
    stats = {"pages": len(pages), "sections": n_sections, "sentences": n_sentences}
    return header + "\n".join(body).rstrip() + "\n", stats


def _body_only(markdown: str) -> str:
    """The file without its timestamped header, for change detection."""
    return re.sub(r"^<!--.*?-->\s*", "", markdown, flags=re.S)


# --------------------------------------------------------------------------
# public
# --------------------------------------------------------------------------
def _state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def age_hours() -> float | None:
    checked = _state().get("checked_at")
    if checked is None:
        if not OUT_FILE.exists():
            return None
        checked = OUT_FILE.stat().st_mtime
    return (time.time() - float(checked)) / 3600


def sync(max_age_hours: float = 24, force: bool = False) -> dict:
    """Refetch the site when the copy is older than `max_age_hours`.

    Returns a summary; `changed` says whether the knowledge file was rewritten
    (and so whether the index needs rebuilding). A failed or empty crawl never
    replaces a good file.
    """
    age = age_hours()
    if not force and age is not None and age < max_age_hours:
        return {"status": "fresh", "changed": False, "age_hours": round(age, 2), "file": str(OUT_FILE)}

    started = time.time()
    pages, errors = crawl()
    markdown, stats = render(pages)
    result = {**stats, "errors": errors, "file": str(OUT_FILE), "seconds": round(time.time() - started, 1)}

    if not pages or stats["sentences"] == 0:
        return {**result, "status": "failed", "changed": False}

    old = OUT_FILE.read_text(encoding="utf-8") if OUT_FILE.exists() else ""
    changed = _body_only(old) != _body_only(markdown)
    if changed:
        OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = OUT_FILE.with_suffix(".tmp")
        tmp.write_text(markdown, encoding="utf-8")
        tmp.replace(OUT_FILE)

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({"checked_at": time.time(), **stats}))
    return {**result, "status": "updated" if changed else "unchanged", "changed": changed}


if __name__ == "__main__":
    summary = sync(force="--force" in sys.argv)
    print(json.dumps(summary, indent=2))
    if summary.get("changed"):
        print("Knowledge changed — run `python -m app.ingest` or POST /api/reindex.")

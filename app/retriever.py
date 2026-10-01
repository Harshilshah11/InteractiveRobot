"""Hybrid retrieval: BM25 (keywords) + dense vectors (meaning), fused.

Fusion picks the candidates; a separately calibrated confidence score decides
whether we are allowed to answer at all. Rank-fusion scores are not
comparable across queries, so they must never be used as the threshold.
"""

from __future__ import annotations

import math
from collections import Counter

from . import embedder
from .config import OOV_PENALTY, STRONG_WEIGHT, TOP_K
from .text import tokenize

BM25_K1 = 1.5
BM25_B = 0.75
RRF_K = 60

# Cosine range that separates noise from a real hit for bge-class models.
# Measured, not guessed: bge-small puts unrelated pairs around 0.44-0.50 and
# good matches around 0.68-0.80, so absolute cosine is squeezed into a narrow
# band and has to be rescaled before it can be compared to a threshold.
COS_FLOOR = 0.50
COS_CEIL = 0.78


def stem(word: str) -> str:
    """Deliberately crude suffix stripping — enough to match plurals/tenses."""
    for suffix in ("ing", "ies", "es", "ed", "s"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return word


class Retriever:
    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        self.doc_tokens = [c["tokens"] for c in chunks]
        self.doc_stems = [{stem(t) for t in toks} for toks in self.doc_tokens]
        self.doc_len = [len(t) for t in self.doc_tokens]
        self.avg_len = (sum(self.doc_len) / len(self.doc_len)) if self.doc_len else 0.0
        self.freqs = [Counter(t) for t in self.doc_tokens]

        df: Counter[str] = Counter()
        for toks in self.doc_tokens:
            df.update(set(toks))
        n = len(chunks)
        self.idf = {
            term: math.log(1 + (n - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }
        self.has_vectors = any(c.get("vector") for c in chunks)
        self.vocab = {stem(term) for term in self.idf}

        # Direct section lookup, keyed on the last segment of the heading
        # path ("Products > Saibya specifications" -> "saibya specifications").
        # Retrieval finds the section that answers the question asked; this is
        # for reading a *named* section the answerer already decided it wants.
        # Sections are written short enough to fit one window, so the first
        # chunk is the whole section; later windows would only repeat overlap.
        self.sections: dict[str, dict] = {}
        for chunk in chunks:
            key = (chunk.get("heading") or "").split(">")[-1].strip().lower()
            if key:
                self.sections.setdefault(key, chunk)

    def section(self, heading: str) -> dict | None:
        return self.sections.get(heading.strip().lower())

    def covers(self, question: str, chunk: dict) -> float:
        """IDF-weighted share of the question's words this chunk contains.

        The same measure ranking uses, exposed for a chunk picked by name
        rather than by rank — it settles which of two candidate sections
        actually holds the fact that was asked for.
        """
        terms = set(tokenize(question))
        if not terms:
            return 0.0
        present = {stem(t) for t in chunk.get("tokens", [])}
        total = hit = 0.0
        for term in terms:
            weight = self.idf.get(term, math.log(1 + len(self.chunks)))
            total += weight
            if stem(term) in present:
                hit += weight
        return hit / total if total else 0.0

    # -- individual retrievers ------------------------------------------
    def _bm25(self, query_tokens: list[str]) -> list[tuple[int, float]]:
        scores = []
        for i, freq in enumerate(self.freqs):
            score = 0.0
            for term in query_tokens:
                tf = freq.get(term, 0)
                if not tf:
                    continue
                denom = tf + BM25_K1 * (
                    1 - BM25_B + BM25_B * self.doc_len[i] / (self.avg_len or 1)
                )
                score += self.idf.get(term, 0.0) * tf * (BM25_K1 + 1) / denom
            if score > 0:
                scores.append((i, score))
        scores.sort(key=lambda x: -x[1])
        return scores[: TOP_K * 3]

    def _dense(self, query_vector: list[float] | None) -> list[tuple[int, float]]:
        if not query_vector or not self.has_vectors:
            return []
        scores = [
            (i, embedder.cosine(query_vector, c["vector"]))
            for i, c in enumerate(self.chunks)
            if c.get("vector")
        ]
        scores.sort(key=lambda x: -x[1])
        return scores[: TOP_K * 3]

    # -- scoring ---------------------------------------------------------
    def _coverage(self, query_tokens: list[str], idx: int) -> float:
        """Share of the question's content words that the chunk actually has.

        Rare words count more than common ones, so matching "reimbursement"
        outweighs matching "policy".
        """
        if not query_tokens:
            return 0.0
        chunk = self.doc_stems[idx]
        total = 0.0
        hit = 0.0
        for term in set(query_tokens):
            weight = self.idf.get(term, math.log(1 + len(self.chunks)))
            total += weight
            if stem(term) in chunk:
                hit += weight
        return hit / total if total else 0.0

    def _confidence(
        self, query_tokens: list[str], idx: int, cosine_score: float | None
    ) -> float:
        coverage = self._coverage(query_tokens, idx)
        if cosine_score is None:
            return coverage

        dense = (cosine_score - COS_FLOOR) / (COS_CEIL - COS_FLOOR)
        dense = min(1.0, max(0.0, dense))

        # Take the stronger channel and let the weaker one top it up. A plain
        # weighted sum would cap a paraphrase that the keywords miss entirely,
        # so semantic-only hits could never clear the threshold.
        strong, weak = max(dense, coverage), min(dense, coverage)
        return STRONG_WEIGHT * strong + (1 - STRONG_WEIGHT) * weak

    def _oov_ratio(self, query_tokens: list[str]) -> float:
        """Share of the question's content words absent from the whole corpus.

        This is what separates "tell me about Saibya" from "how much does
        Saibya cost". Both match the Saibya chunk semantically, because the
        topic is identical — but `cost` occurs nowhere in the knowledge base,
        which is decisive evidence that the answer is not there. Similarity to
        the right *topic* is not the same as having the requested *fact*.
        """
        terms = {stem(t) for t in query_tokens if len(t) > 2}
        if not terms:
            return 0.0
        return len(terms - self.vocab) / len(terms)

    # -- public ----------------------------------------------------------
    def search(self, question: str) -> list[dict]:
        query_tokens = tokenize(question)
        if not query_tokens:
            query_tokens = tokenize(question, keep_stopwords=True)
        # Scales every candidate's confidence down together, so it can only
        # trigger a refusal — it never reorders the results.
        oov = self._oov_ratio(query_tokens)
        grounding = 1.0 - OOV_PENALTY * oov

        lexical = self._bm25(query_tokens)
        query_vector = embedder.embed_query(question) if self.has_vectors else None
        dense = self._dense(query_vector)

        # Reciprocal rank fusion — robust to the two scores being on
        # completely different scales.
        fused: dict[int, float] = {}
        for ranking in (lexical, dense):
            for rank, (idx, _) in enumerate(ranking):
                fused[idx] = fused.get(idx, 0.0) + 1.0 / (RRF_K + rank + 1)

        results = []
        for idx, fusion_score in sorted(fused.items(), key=lambda x: -x[1])[:TOP_K]:
            chunk = self.chunks[idx]
            # Score the cosine for every candidate, not just those the dense
            # retriever shortlisted. Reusing only the dense top-K let a
            # keyword-only hit fall back to coverage alone and score a
            # perfect 1.0 despite the embedder ranking it nowhere.
            cosine = (
                embedder.cosine(query_vector, chunk["vector"])
                if query_vector and chunk.get("vector")
                else None
            )
            results.append(
                {
                    "text": chunk["text"],
                    "heading": chunk["heading"],
                    "source": chunk["source"],
                    "aliases": chunk.get("aliases", ""),
                    "confidence": round(
                        self._confidence(query_tokens, idx, cosine) * grounding, 4
                    ),
                    "fusion": round(fusion_score, 5),
                    "cosine": round(cosine or 0.0, 4),
                    # A property of the question, not the chunk, but carried on
                    # every row so the answerer can tell "badly phrased" from
                    # "not in here" without re-tokenising the query.
                    "oov": round(oov, 4),
                }
            )

        # Re-order by calibrated confidence: fusion chose the shortlist,
        # confidence decides which one we actually read out.
        results.sort(key=lambda r: -r["confidence"])
        return results

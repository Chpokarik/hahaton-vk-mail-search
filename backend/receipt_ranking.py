"""Rank messages already scoped to a mailbox and receipt day."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence


_CARRIER_WORDS = {"письмо", "уведомление", "сообщение", "получение"}
_LONG_RUSSIAN_WORD = re.compile(r"[а-яё]{7,}")


class ReceiptRanker:
    """Score topic coverage and lead/title matches within one day's candidates."""

    def __init__(self, terms: Iterable[str], stopwords: set[str]) -> None:
        self.terms = set(terms) - stopwords - _CARRIER_WORDS
        self.prefixes: dict[str, set[str]] = defaultdict(set)
        for term in self.terms:
            # A long common prefix can connect an event noun with its verb.
            # Keep this rule away from numbers and short or Latin tokens.
            if _LONG_RUSSIAN_WORD.fullmatch(term):
                self.prefixes[term[:6]].add(term)

    def _matches(self, token: str) -> Iterable[str]:
        if token in self.terms:
            yield token
        if len(token) >= 7:
            yield from self.prefixes.get(token[:6], ())

    def score(
        self,
        tokens: Sequence[str],
        subject: Mapping[str, int],
        lexical: float | None,
    ) -> float | None:
        positions: dict[str, int] = {}
        for index, token in enumerate(tokens):
            for term in self._matches(token):
                positions.setdefault(term, index)
            if len(positions) == len(self.terms):
                break
        if not positions:
            return lexical

        total = len(self.terms)
        coverage = len(positions) / total
        early = math.fsum(1 / (1 + index / 18) for index in positions.values()) / total
        subject_terms = {term for token in subject for term in self._matches(token)}
        subject_coverage = len(subject_terms & positions.keys()) / total
        proximity = 0.0
        if len(positions) > 1:
            span = max(positions.values()) - min(positions.values())
            proximity = 1 / (1 + span / 6)
        return (lexical or 0) + coverage + 2 * early + 1.5 * subject_coverage + 0.6 * proximity

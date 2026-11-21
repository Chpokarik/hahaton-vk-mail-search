"""Interpret receipt dates in Russian mail queries."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta


MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}
RELATIVE_DAYS = {"позавчера": 2, "вчера": 1, "сегодня": 0}
DATE_RE = re.compile(
    r"(?<![\w.])(?:"
    r"(?P<iso>\d{4}-\d{2}-\d{2})|"
    r"(?P<relative>позавчера|вчера|сегодня)|"
    r"(?P<dot_day>\d{1,2})\.(?P<dot_month>\d{1,2})(?:\.(?P<dot_year>\d{4}|\d{2}))?|"
    rf"(?P<day>\d{{1,2}})\s+(?P<month>{'|'.join(MONTHS)})(?:\s+(?P<year>\d{{4}}))?"
    r")(?!\w|\.\d)(?:\s+года\b)?",
    re.IGNORECASE,
)
DATE_CONTEXT = re.compile(
    r"\b(?:полученн\w*|пришедш\w*|поступивш\w*|приш[её]л|пришла|пришли)\s*$",
    re.IGNORECASE,
)
RANGE_PREFIX = re.compile(r"\b(?:с|со|до|после|между|раньше|позже)\s*$", re.IGNORECASE)
QUERY_PREFIX = re.compile(
    r"^\s*(?:(?:пожалуйста|найди(?:те)?|покажи(?:те)?|отыщи(?:те)?|ищу)\b[\s,]+)+",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ReceiptQuery:
    text: str
    day: date | None = None


def parse_receipt_query(text: str, reference: date | None) -> ReceiptQuery:
    query = QUERY_PREFIX.sub("", text)
    matches = list(DATE_RE.finditer(query))
    if len(matches) != 1:
        return ReceiptQuery(query)
    match = matches[0]
    before = query[:match.start()]
    if RANGE_PREFIX.search(before):
        return ReceiptQuery(query)
    anchor = reference or date.today()
    try:
        if match["relative"]:
            day = anchor - timedelta(days=RELATIVE_DAYS[match["relative"].lower()])
        elif match["iso"]:
            day = date.fromisoformat(match["iso"])
        else:
            month = int(match["dot_month"]) if match["dot_month"] else MONTHS[match["month"].lower()]
            raw_year = match["year"] or match["dot_year"]
            year = int(raw_year) if raw_year else anchor.year
            if raw_year and len(raw_year) == 2:
                year += 2000
            day = date(year, month, int(match["day"] or match["dot_day"]))
            if not raw_year and day > anchor:
                day = day.replace(year=day.year - 1)
    except (ValueError, OverflowError):
        return ReceiptQuery(query)

    before = DATE_CONTEXT.sub("", before)
    after = query[match.end():]
    return ReceiptQuery(f"{before} {after}".strip(" ,.;"), day)

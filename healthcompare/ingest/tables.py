"""Check transcribed premium tables against the document text, row by row.

A row is accepted only if its premiums appear, in order, among the numbers
printed on the cited page (or the next one), with the first values adjacent.
Anything that fails is dropped rather than trusted.
"""

from __future__ import annotations

import re

_NUM = re.compile(r"\d[\d,]*")


def page_numbers(text: str) -> list[list[int]]:
    """Numbers per page of a pdftotext file (pages split on form feeds), commas removed."""
    out = []
    for page in text.split("\f"):
        nums = []
        for tok in _NUM.findall(page):
            digits = tok.replace(",", "")
            if digits:
                nums.append(int(digits))
        out.append(nums)
    return out


def _is_subsequence(values: list[int], stream: list[int], adjacent_prefix: int) -> bool:
    """values appear in order in stream; the first `adjacent_prefix` of them back to back."""
    k = min(adjacent_prefix, len(values))
    head = values[:k]
    for start in range(len(stream) - k + 1):
        if stream[start:start + k] != head:
            continue
        pos = start + k
        ok = True
        for v in values[k:]:
            try:
                pos = stream.index(v, pos) + 1
            except ValueError:
                ok = False
                break
        if ok:
            return True
    return False


def verify_row(premiums: list[int | None], pages: list[list[int]], page: int | None) -> bool:
    """Tables can continue onto the next page (extra sum-insured columns), so each
    candidate page is checked together with the page after it."""
    values = [v for v in premiums if v is not None]
    if not values:
        return False
    starts = range(len(pages)) if page is None else [i for i in range(page - 2, page + 4) if 0 <= i < len(pages)]
    return any(_is_subsequence(values, pages[i] + (pages[i + 1] if i + 1 < len(pages) else []), 3) for i in starts)


def verify_table(table: dict, pages: list[list[int]]) -> dict:
    """Return a copy with only verified rows, plus counts."""
    kept = [r for r in table["rows"] if verify_row(r["premiums"], pages, table.get("page"))]
    if not kept:  # page number may be off: retry against the whole document
        kept = [r for r in table["rows"] if verify_row(r["premiums"], pages, None)]
    out = dict(table, rows=kept)
    out["rows_checked"] = len(table["rows"])
    out["rows_verified"] = len(kept)
    return out

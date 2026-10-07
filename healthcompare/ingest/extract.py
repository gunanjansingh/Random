"""Extract criterion values from policy documents, with quotes we can check.

Two extractors produce the same `Candidate` shape:
  * `rule_candidates`: regexes for formulaic clauses (UIN, waiting periods, pre/post days)
  * `claude_candidates`: Claude reads the whole PDF and returns JSON per criterion

Every candidate's quote is then checked against text extracted locally from
the PDF (`validate`). A value whose quote is not in the document is dropped:
the model is never trusted on its own word.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path

from ..criteria import BY_ID, CRITERIA, Criterion, Kind

MODEL = "claude-opus-5-5"


@dataclass
class Candidate:
    criterion: str
    value: object
    quote: str
    page: int | None
    confidence: float
    extractor: str  # "rule" | "claude"
    note: str = ""
    validated: bool = False


# --------------------------------------------------------------------------- PDF text

def page_texts(pdf_path: Path) -> list[str]:
    """Text per page (index 0 = page 1). Requires `pip install pypdf`."""
    from pypdf import PdfReader

    return [page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages]


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"-\s*\n\s*", "", s)  # de-hyphenate line breaks
    return re.sub(r"[^a-z0-9%.]+", " ", s.lower()).strip()


def validate(c: Candidate, pages: list[str]) -> bool:
    """True if the candidate's quote appears on its page (or a neighbour)."""
    q = _norm(c.quote)
    if len(q) < 12:
        return False
    idx = range(len(pages)) if c.page is None else range(max(0, c.page - 2), min(len(pages), c.page + 1))
    joined = " ".join(_norm(pages[i]) for i in idx)
    return q in joined


# --------------------------------------------------------------------------- rule extractor

_WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "thirty": 30, "sixty": 60, "ninety": 90}
_N = r"(\d{1,3}|one|two|three|four|thirty|sixty|ninety)"
RULES: dict[str, list[tuple[re.Pattern, float]]] = {
    "ped_waiting_months": [(re.compile(rf"pre-?\s?existing[^.]{{0,200}}?expiry of {_N} \(?\w*\)?\s*months", re.I | re.S), 1)],
    "specific_disease_waiting_months": [(re.compile(rf"specified[^.]{{0,200}}?expiry of {_N} \(?\w*\)?\s*months", re.I | re.S), 1)],
    "initial_waiting_days": [(re.compile(rf"within {_N} days from the first policy commencement", re.I), 1)],
    "pre_hosp_days": [(re.compile(rf"pre-?\s?hospitali[sz]ation[^.]{{0,120}}?{_N} days", re.I | re.S), 1)],
    "post_hosp_days": [(re.compile(rf"post-?\s?hospitali[sz]ation[^.]{{0,120}}?{_N} days", re.I | re.S), 1)],
}
UIN_RE = re.compile(r"\b[A-Z]{4,6}LIP\d{5}V\d{6}\b")


def _num(tok: str) -> float:
    return float(_WORD_NUM.get(tok.lower(), tok))


def rule_candidates(pages: list[str]) -> tuple[list[Candidate], set[str]]:
    """Regex candidates (first hit per criterion) and every UIN seen."""
    out: list[Candidate] = []
    uins: set[str] = set()
    for i, text in enumerate(pages):
        uins.update(UIN_RE.findall(text))
    for cid, patterns in RULES.items():
        for pat, scale in patterns:
            for i, text in enumerate(pages):
                m = pat.search(text)
                if m:
                    out.append(Candidate(cid, _num(m.group(1)) * scale, " ".join(m.group(0).split()), i + 1, 0.6, "rule"))
                    break
            else:
                continue
            break
    return out, uins


# --------------------------------------------------------------------------- Claude extractor

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "values": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "criterion": {"type": "string", "enum": [c.id for c in CRITERIA]},
                    "value": {"type": "string"},
                    "quote": {"type": "string"},
                    "page": {"type": "integer"},
                    "confidence": {"type": "number"},
                    "note": {"type": "string"},
                },
                "required": ["criterion", "value", "quote", "page", "confidence", "note"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["values"],
    "additionalProperties": False,
}


def _criterion_line(c: Criterion) -> str:
    if c.kind is Kind.ENUM:
        fmt = "one of: " + ", ".join(c.options)
    elif c.kind is Kind.BOOL:
        fmt = "true or false"
    elif c.kind is Kind.NUMBER:
        fmt = f"a number{f' in {c.unit}' if c.unit else ''}"
    else:
        fmt = "short text"
    return f"- {c.id}: {c.label}. Value: {fmt}. Context: {c.why}"


def build_prompt(plan_name: str, doc_type: str, criteria: list[Criterion]) -> str:
    lines = "\n".join(_criterion_line(c) for c in criteria)
    return f"""You are extracting terms from an Indian health insurance {doc_type.replace('_', ' ')} for "{plan_name}", to power an honest comparison tool. People will rely on these values when choosing cover, so a wrong value is worse than a missing one.

For each criterion below that the document states, return one entry:
- value: as a string in the format given (numbers as plain digits, e.g. "36"; booleans "true"/"false").
- quote: the exact sentence from the document that states it, copied verbatim (up to ~300 characters). It will be string-matched against the PDF text, so do not paraphrase or join text from different places.
- page: the 1-based PDF page the quote is on.
- confidence: 0 to 1.
- note: anything that qualifies the value: optional add-on vs base cover, applies only to a variant or zone, "unless specified in the schedule", etc. Empty string if none.

Describe the base plan. If a benefit exists only as an optional add-on, give the base-plan value and say so in the note. Skip criteria the document does not address; do not infer from general insurance knowledge or IRDAI defaults.

Criteria:
{lines}"""


def _coerce(c: Criterion, raw: str) -> object:
    raw = raw.strip()
    if c.kind is Kind.NUMBER:
        return float(re.sub(r"[^\d.]", "", raw))
    if c.kind is Kind.BOOL:
        if raw.lower() not in ("true", "false"):
            raise ValueError(raw)
        return raw.lower() == "true"
    if c.kind is Kind.ENUM and raw not in c.options:
        raise ValueError(raw)
    return raw


def parse_response(text: str) -> list[Candidate]:
    """Turn the model's JSON into candidates, dropping malformed entries."""
    out = []
    for item in json.loads(text).get("values", []):
        c = BY_ID.get(item.get("criterion", ""))
        if c is None:
            continue
        try:
            value = _coerce(c, str(item["value"]))
        except (ValueError, KeyError):
            continue
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        out.append(Candidate(c.id, value, item.get("quote", ""), item.get("page"),
                             float(item.get("confidence", 0.5)), "claude", item.get("note", "")))
    return out


def claude_candidates(pdf_path: Path, plan_name: str, doc_type: str, criteria: list[Criterion] | None = None) -> list[Candidate]:
    """Ask Claude to read the PDF and extract values. Needs `pip install anthropic`
    and credentials (ANTHROPIC_API_KEY or an `ant auth login` profile)."""
    import anthropic

    client = anthropic.Anthropic()
    pdf_b64 = base64.standard_b64encode(pdf_path.read_bytes()).decode()
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=64000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # re-run on Anthropic's recommended fallback model if declined
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
        messages=[{"role": "user", "content": [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64}},
            {"type": "text", "text": build_prompt(plan_name, doc_type, criteria or list(CRITERIA))},
        ]}],
    ) as stream:
        response = stream.get_final_message()
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Extraction declined for {pdf_path}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError(f"Extraction output truncated for {pdf_path}")
    text = next(b.text for b in response.content if b.type == "text")
    return parse_response(text)


# --------------------------------------------------------------------------- per-document run

def extract_document(pdf_path: Path, plan_name: str, doc_type: str, use_claude: bool = True,
                     criteria: list[Criterion] | None = None) -> dict:
    pages = page_texts(pdf_path)
    rules, uins = rule_candidates(pages)
    llm = claude_candidates(pdf_path, plan_name, doc_type, criteria) if use_claude else []
    kept: list[Candidate] = []
    for c in rules + llm:
        c.validated = validate(c, pages)
        if c.validated:
            kept.append(c)
    # Rule and model agreeing on a value is stronger evidence.
    by_crit: dict[str, list[Candidate]] = {}
    for c in kept:
        by_crit.setdefault(c.criterion, []).append(c)
    for group in by_crit.values():
        if len({str(c.value) for c in group}) == 1 and len({c.extractor for c in group}) > 1:
            for c in group:
                c.confidence = max(c.confidence, 0.95)
    return {
        "doc_type": doc_type,
        "uins": sorted(uins),
        "pages": len(pages),
        "candidates": [c.__dict__ for c in kept],
        "dropped": len(rules) + len(llm) - len(kept),
    }

"""Merge extracted candidates into the plan dataset.

Rules:
  * Only quote-validated candidates are applied.
  * The most authoritative document wins (models.SOURCE_PRECEDENCE), then confidence.
  * Disagreeing values are kept as `alternates` and surface in the app as
    "sources disagree", so a human can look before it matters.
  * A value becomes `verified` when its quote was found in a filed document
    (policy wording, CIS or prospectus).
"""

from __future__ import annotations

from datetime import date

from ..models import SOURCE_PRECEDENCE

FILED_DOCS = {"policy_wording", "customer_information_sheet", "prospectus"}


def _rank(source: str) -> int:
    return SOURCE_PRECEDENCE.index(source) if source in SOURCE_PRECEDENCE else len(SOURCE_PRECEDENCE)


def _as_value(cand: dict, doc_type: str, url: str) -> dict:
    out = {
        "value": cand["value"],
        "confidence": round(cand["confidence"], 2),
        "verified": doc_type in FILED_DOCS and cand.get("validated", False),
        "citation": {"source": doc_type, "url": url, "quote": cand["quote"], "page": cand["page"],
                     "retrieved": date.today().isoformat()},
    }
    if cand.get("note"):
        out["note"] = cand["note"]
    return out


def merge_value(existing: dict | None, incoming: dict) -> dict:
    """Pick the better-sourced of two values; keep the other as an alternate if it disagrees."""
    if existing is None:
        return incoming
    def key(v: dict) -> tuple:
        return (_rank(v.get("citation", {}).get("source", "")), not v.get("verified", False), -v.get("confidence", 0))
    winner, loser = sorted([existing, incoming], key=key)
    winner = dict(winner)
    alts = [a for a in winner.get("alternates", []) + loser.get("alternates", [])]
    if loser["value"] != winner["value"]:
        alts.append({k: v for k, v in loser.items() if k != "alternates"})
    if alts:
        winner["alternates"] = alts
    return winner


def apply_extractions(plans_doc: dict, extractions: dict[str, list[dict]]) -> dict[str, int]:
    """Apply `{plan_id: [extract_document() results]}` to the loaded plans JSON in place.
    Returns the number of values changed per plan."""
    changed: dict[str, int] = {}
    by_id = {p["id"]: p for p in plans_doc["plans"]}
    for plan_id, docs in extractions.items():
        plan = by_id.get(plan_id)
        if plan is None:
            continue
        n = 0
        for doc in docs:
            url = plan.get("documents", {}).get(doc["doc_type"], "")
            if doc.get("uins") and not plan.get("uin"):
                plan["uin"] = doc["uins"][0]
            for cand in doc["candidates"]:
                if not cand.get("validated"):
                    continue
                cid = cand["criterion"]
                new = merge_value(plan["values"].get(cid), _as_value(cand, doc["doc_type"], url))
                if new != plan["values"].get(cid):
                    plan["values"][cid] = new
                    n += 1
        changed[plan_id] = n
    return changed

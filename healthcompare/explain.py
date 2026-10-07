"""Reasons behind each suggestion: which filters a plan passed, what it does well on
the things the user said matter, and its trade-offs. Every reason carries its source."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from .criteria import BY_ID, Kind
from .engine import NEUTRAL, ScoreCard, _effective, weights_for, with_derived
from .india import inr
from .models import CitedValue, Plan, UserProfile


# Required of every plan by regulation, so never a reason to prefer one plan.
BASELINE = {"lifelong_renewal", "mental_health_parity", "hiv_std_covered", "moratorium_months"}


def _short_why(cid: str) -> str:
    why = BY_ID[cid].why
    first = re.split(r"(?<!etc)(?<!e\.g)\.\s", why, maxsplit=1)[0].rstrip(".")
    return first if len(first) <= 160 else first[:157] + "..."


@dataclass
class Reason:
    kind: str  # "filter" | "unconfirmed" | "strength" | "tradeoff"
    text: str
    source: str = ""


def source_of(cv: CitedValue | None) -> str:
    if cv is None:
        return ""
    if cv.citation is None:
        return "derived" if cv.note.startswith("Derived") else ""
    host = urlsplit(cv.citation.url).netloc.removeprefix("www.")
    return f"{host}, {'verified' if cv.verified else 'unverified'}"


def show(cid: str, value: object) -> str:
    c = BY_ID[cid]
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, str):
        return value.replace("_", " ")
    if c.unit == "Rs":
        return inr(value)
    return f"{value:g}{'%' if c.unit.startswith('%') else f' {c.unit}' if c.unit else ''}"


def _filter_checks(plan: Plan, user: UserProfile) -> list[tuple[str, str, object]]:
    """(filter label, criterion id, test) for each deal-breaker the user set."""
    db = user.deal_breakers
    out = []
    if db.no_room_rent_cap:
        out.append(("No room-rent cap", "room_rent_limit", lambda v: v in ("no_limit", "any_room_except_suite")))
    if db.no_copay:
        out.append(("No co-pay", "general_copay_pct", lambda v: v == 0))
    if db.no_disease_sublimits:
        out.append(("No disease sub-limits", "disease_sublimits", lambda v: v == "none"))
    if db.max_ped_wait_months is not None and user.has_ped:
        out.append((f"Pre-existing disease wait at most {db.max_ped_wait_months} months", "ped_waiting_months",
                     lambda v: v <= db.max_ped_wait_months))
    if db.need_maternity:
        out.append(("Maternity covered", "maternity_covered", lambda v: v is True))
    if db.min_csr_amount is not None:
        out.append((f"Claim settlement by amount at least {db.min_csr_amount:g}%", "csr_amount",
                     lambda v: v >= db.min_csr_amount))
    return out


def explain(card: ScoreCard, others: list[ScoreCard], user: UserProfile, n: int = 3) -> list[Reason]:
    plan = with_derived(card.plan, user.sum_insured)
    reasons: list[Reason] = []

    for label, cid, ok in _filter_checks(plan, user):
        cv = plan.values.get(cid)
        if cv is None:
            reasons.append(Reason("unconfirmed", f"'{label}': not confirmed yet ({BY_ID[cid].label} unknown); ask the insurer"))
        elif ok(cv.value):
            reasons.append(Reason("filter", f"'{label}': {BY_ID[cid].label.lower()} is {show(cid, cv.value)}", source_of(cv)))

    weights = weights_for(user)
    other_plans = [with_derived(o.plan, user.sum_insured) for o in others if o.plan.id != card.plan.id]
    contrib = []
    for cid, w in weights.items():
        cv = plan.values.get(cid)
        raw = BY_ID[cid].score(cv.value) if cv else None
        if raw is None:
            continue
        contrib.append(((_effective(cv, raw) - NEUTRAL) * w, cid, cv, raw))

    def others_known(cid: str) -> list[float]:
        return [s for s in (BY_ID[cid].score(o.get(cid)) for o in other_plans) if s is not None]

    def comparison(cid: str, raw: float, better: bool) -> str:
        known = others_known(cid)
        if not known:
            return ""
        if better and raw > max(known):
            return " (best among the plans that fit your filters)"
        if not better and raw < min(known):
            return " (weakest among the plans that fit your filters)"
        return ""

    used = {r.text.split("'")[1] for r in reasons if "'" in r.text}
    for c, cid, cv, raw in sorted(contrib, key=lambda t: -t[0]):
        if len([r for r in reasons if r.kind == "strength"]) >= n or c <= 0 or raw < 0.75:
            break
        if cid in BASELINE or (cid == "room_rent_limit" and "No room-rent cap" in used):
            continue
        known = others_known(cid)
        if known and all(k >= raw for k in known):
            continue  # every other plan is at least as good here: not a reason to pick this one
        reasons.append(Reason("strength", f"{BY_ID[cid].label}: {show(cid, cv.value)}{comparison(cid, raw, True)}. "
                                          f"{_short_why(cid)}.", source_of(cv)))

    for c, cid, cv, raw in sorted(contrib, key=lambda t: t[0]):
        if len([r for r in reasons if r.kind == "tradeoff"]) >= n or c >= 0 or raw > 0.35:
            break
        if cid == "ped_waiting_months" and user.has_ped:
            continue  # the personal warning below says it better
        known = others_known(cid)
        if cid in BASELINE or (known and all(k <= raw for k in known)):
            continue  # every other plan is the same or worse here: not a reason against this one
        note = (f" ({cv.note.rstrip('.')})" if cv.note and len(cv.note) <= 90 and not cv.note.startswith("Derived")
                else f" ({cv.period})" if cv.period else "")
        reasons.append(Reason("tradeoff", f"{BY_ID[cid].label}: {show(cid, cv.value)}{comparison(cid, raw, False)}{note}",
                              source_of(cv)))
    for g in card.gotchas:
        if g.severity == "high" and len([r for r in reasons if r.kind == "tradeoff"]) < n + 1:
            reasons.append(Reason("tradeoff", g.text))
    return reasons


def headline(cards: list[ScoreCard]) -> str:
    first = cards[0]
    tied = [c for c in cards[1:] if c.score_range[1] > first.score_range[0]]
    if not tied:
        return f"Based on our conversation and your filters, the best-suited plan for you is {first.plan.label()}."
    why = ("much of their fine print is still unverified" if min(c.coverage for c in [first, *tied]) < 0.5
           else "they are nearly tied on what matters to you")
    return (f"Based on our conversation and your filters, {first.plan.label()} is the best-suited plan, but it is a close "
            f"call with {', '.join(c.plan.label() for c in tied)} ({why}), so compare the reasons below rather than the "
            f"score alone.")

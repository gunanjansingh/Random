"""Matching engine: hard filters -> weighted scoring -> personal gotchas -> claim simulation."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from . import india
from .criteria import BY_ID, CRITERIA, Category, Kind
from .india import inr
from .models import ZONE_COST_RANK, CitedValue, Member, Plan, UserProfile

# Unknown values score neutral: with real data, gaps mostly reflect what has
# been extracted so far, not the plan. Coverage is reported next to the score,
# and low-confidence values are pulled toward neutral (see `_effective`).
NEUTRAL = 0.5


def with_derived(plan: Plan, sum_insured: int | None = None) -> Plan:
    """Copy of `plan` evaluated at `sum_insured`, plus values implied by others."""
    p = replace(plan, values=dict(plan.values), sum_insured=sum_insured or plan.sum_insured)
    if p.get("room_rent_limit") == "no_limit" and "proportionate_deduction" not in p.values:
        src = p.values["room_rent_limit"]
        p.values["proportionate_deduction"] = CitedValue(
            False, src.citation, src.confidence, src.verified,
            note="Derived: no room cap, so proportionate deduction cannot trigger")
    return p


def _effective(cv: CitedValue | None, raw: float | None) -> float:
    if raw is None or cv is None:
        return NEUTRAL
    return NEUTRAL + (raw - NEUTRAL) * max(0.0, min(1.0, cv.confidence))


# --------------------------------------------------------------------------- premium

def member_premium(plan: Plan, age: int) -> int:
    bands = sorted(b for b in plan.premium_by_age if b <= age)
    if not bands:
        bands = [min(plan.premium_by_age)]
    return plan.premium_by_age[bands[-1]]


def annual_premium(plan: Plan, members: list[Member]) -> int | None:
    """Indicative annual premium, or None when no premium table is loaded.
    GST is nil on individual health policies from 22 Sep 2025."""
    if not plan.premium_by_age:
        return None
    total = sum(member_premium(plan, m.age) for m in members)
    if len(members) > 1:
        total *= 1 - plan.floater_discount_pct / 100
    return round(total)


# --------------------------------------------------------------------------- hard filters

@dataclass
class FilterResult:
    failures: list[str] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)

    @property
    def eligible(self) -> bool:
        return not self.failures


def check_deal_breakers(plan: Plan, user: UserProfile) -> FilterResult:
    db, r = user.deal_breakers, FilterResult()

    def need(cid: str, ok, msg: str) -> None:
        v = plan.get(cid)
        if v is None:
            r.unverified.append(f"{BY_ID[cid].label}: not known (ask insurer)")
        elif not ok(v):
            r.failures.append(msg.format(v=v))

    max_age = plan.get("max_entry_age")
    if isinstance(max_age, (int, float)) and user.oldest > max_age:
        r.failures.append(f"Entry age limit {max_age}; oldest member is {user.oldest}")
    if db.no_room_rent_cap:
        need("room_rent_limit", lambda v: v in ("no_limit", "any_room_except_suite"), "Room rent capped ({v})")
    if db.no_copay:
        need("general_copay_pct", lambda v: v == 0, "Co-pay of {v}% on every claim")
        if any(m.age >= (plan.get("age_copay_from_age") or 999) for m in user.members):
            need("age_copay_pct", lambda v: v == 0, "Age-based co-pay of {v}% applies to your family")
    if db.no_disease_sublimits:
        need("disease_sublimits", lambda v: v == "none", "Disease sub-limits: {v}")
    if db.max_ped_wait_months is not None and user.has_ped:
        need("ped_waiting_months", lambda v: v <= db.max_ped_wait_months, "PED waiting {v} months")
    if db.need_maternity:
        need("maternity_covered", lambda v: v is True, "No maternity cover")
    if db.min_csr_amount is not None:
        need("csr_amount", lambda v: v >= db.min_csr_amount, "Claim settlement by amount only {v}%")
    if db.preferred_hospitals_cashless:
        missing = [h for h in user.preferred_hospitals if h not in plan.network_hospitals]
        if missing:
            r.failures.append(f"Not cashless at: {', '.join(missing)}")
    if db.max_premium is not None:
        p = annual_premium(plan, user.members)
        if p is None:
            r.unverified.append("Premium: no premium table loaded (get a quote)")
        elif p > db.max_premium:
            r.failures.append(f"Premium {inr(p)} over budget {inr(db.max_premium)}")
    return r


# --------------------------------------------------------------------------- scoring

def weights_for(user: UserProfile) -> dict[str, float]:
    has_senior = user.oldest >= 50
    out: dict[str, float] = {}
    for c in CRITERIA:
        if c.kind is Kind.TEXT:
            continue
        w = c.weight * user.priorities.get(c.category, 3) / 3
        if "ped" in c.tags:
            w *= 3 if user.has_ped else 0.5
        if "maternity" in c.tags:
            w *= 3 if user.planning_pregnancy else 0.1
        if "senior" in c.tags:
            w *= 2.5 if has_senior else 0.4
        if c.id == "zone_copay_pct" and india.zone_for_city(user.city) == "A":
            w *= 2
        out[c.id] = w
    return out


@dataclass
class ScoreCard:
    plan: Plan
    total: float  # 0..100
    by_category: dict[Category, float]
    coverage: float  # share of weight backed by known data
    score_range: tuple[float, float]  # total if every unknown turned out worst / best
    premium: int | None
    filters: FilterResult
    gotchas: list[Gotcha]
    irdai_flags: list[str]
    to_verify: list[str]


def score_plan(plan: Plan, user: UserProfile) -> ScoreCard:
    plan = with_derived(plan, user.sum_insured)
    weights = weights_for(user)
    num = den = known = unknown_num = 0.0
    cat_num: dict[Category, float] = {}
    cat_den: dict[Category, float] = {}
    for cid, w in weights.items():
        crit = BY_ID[cid]
        raw = crit.score(plan.get(cid))
        if raw is not None:
            known += w
        s = _effective(plan.values.get(cid), raw)
        if raw is None:
            unknown_num += s * w
        num += s * w
        den += w
        cat_num[crit.category] = cat_num.get(crit.category, 0) + s * w
        cat_den[crit.category] = cat_den.get(crit.category, 0) + w
    raw_values = {cid: cv.value for cid, cv in plan.values.items()}
    return ScoreCard(
        plan=plan,
        total=round(100 * num / den, 1),
        by_category={c: round(100 * cat_num[c] / cat_den[c]) for c in cat_den if cat_den[c]},
        coverage=round(known / den, 2),
        score_range=(round(100 * (num - unknown_num) / den, 1), round(100 * (num - unknown_num + (den - known)) / den, 1)),
        premium=annual_premium(plan, user.members),
        filters=check_deal_breakers(plan, user),
        gotchas=gotchas(plan, user),
        irdai_flags=[v.message for v in india.irdai_violations(raw_values)],
        to_verify=to_verify(plan, user),
    )


def rank(plans: list[Plan], user: UserProfile, top: int = 3) -> tuple[list[ScoreCard], list[ScoreCard]]:
    """Return (top eligible plans by score, rejected plans)."""
    cards = [score_plan(p, user) for p in plans]
    eligible = sorted((c for c in cards if c.filters.eligible),
                      key=lambda c: (-c.total, c.premium if c.premium is not None else float("inf")))
    rejected = [c for c in cards if not c.filters.eligible]
    return eligible[:top], rejected


# --------------------------------------------------------------------------- verification list

def to_verify(plan: Plan, user: UserProfile, limit: int = 6) -> list[str]:
    """What to confirm before buying: conflicting sources first, then the
    heaviest rejection-risk items that are unknown or low-confidence."""
    out: list[str] = []
    for cid, cv in plan.values.items():
        if cv.conflicting:
            vals = ", ".join(str(a.value) for a in cv.alternates)
            out.append(f"{BY_ID[cid].label}: sources disagree ({cv.value} vs {vals})")
    def add(line: str) -> None:
        if line.split(":")[0] not in {o.split(":")[0] for o in out}:
            out.append(line)

    weights = weights_for(user)
    risky = sorted((c for c in CRITERIA if c.rejection_risk and c.id in weights), key=lambda c: -weights[c.id])
    for c in risky:
        cv = plan.values.get(c.id)
        if cv is None:
            add(f"{c.label}: unknown, ask the insurer")
        elif cv.confidence < 0.5:
            add(f"{c.label}: low-confidence value ({cv.value}){f' ({cv.note})' if cv.note else ''}")
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------- personal gotchas

@dataclass
class Gotcha:
    severity: str  # high | medium | info
    text: str


ROOM_CAP_PCT = {"1pct_si_per_day": 1, "2pct_si_per_day": 2}
# Typical single private room per day in a good private hospital, by zone.
# Used only to illustrate the room-rent trap; the user can override it.
TYPICAL_PRIVATE_ROOM = {"A": 8000, "B": 6000, "C": 4000}


def _poss(name: str) -> str:
    return "Your" if name.lower() == "you" else f"{name}'s"


def _note(plan: Plan, cid: str) -> str:
    cv = plan.values.get(cid)
    return f" Note: {cv.note.rstrip('.')}." if cv and cv.note else ""


def gotchas(plan: Plan, user: UserProfile) -> list[Gotcha]:
    plan = with_derived(plan, user.sum_insured)
    g: list[Gotcha] = []
    v = plan.get
    zone = user.zone_for(plan)

    # Room rent and proportionate deduction: the most common surprise.
    room = v("room_rent_limit")
    if room in ROOM_CAP_PCT:
        cap = plan.sum_insured * ROOM_CAP_PCT[room] / 100
        typical = TYPICAL_PRIVATE_ROOM[zone]
        if v("proportionate_deduction") and typical > cap:
            paid = cap / typical
            g.append(Gotcha("high",
                f"Room rent capped at {inr(cap)}/day. A typical private room in {user.city} costs about "
                f"{inr(typical)}, so proportionate deduction would pay only ~{paid:.0%} of the whole "
                f"bill (doctor, OT, nursing), not just the room."))
    elif room in ("single_private_room", "shared_room") and v("proportionate_deduction"):
        g.append(Gotcha("medium",
            f"Eligible room is '{room.replace('_', ' ')}'. Choosing a deluxe/suite room triggers proportionate "
            "deduction on the whole bill."))

    # Pre-existing diseases.
    ped_wait = v("ped_waiting_months")
    for m in user.members:
        if m.conditions and isinstance(ped_wait, (int, float)) and ped_wait > 0:
            g.append(Gotcha("high",
                f"{_poss(m.name)} {', '.join(m.conditions)} not covered for the first {ped_wait:g} months "
                f"(until about age {m.age + ped_wait / 12:.0f})."
                + (" A PED-waiting reduction add-on is available." if v("ped_waiting_reducible") else "")))
    if user.has_ped and (pw := v("personal_waiting_months")):
        g.append(Gotcha("medium", f"Underwriting can add a personal waiting period of up to {pw:g} months for a declared "
                                   "condition. Check the policy schedule before paying."))
    if user.has_ped and v("ped_permanent_exclusion_option"):
        g.append(Gotcha("high", "Insurer may permanently exclude a declared condition. Check the policy schedule for "
                                 "'permanent exclusion' before paying."))
    med_age = v("pre_policy_medicals_age")
    if isinstance(med_age, (int, float)) and user.oldest < med_age:
        mor = v("moratorium_months") or india.IRDAI_MORATORIUM_MONTHS
        g.append(Gotcha("medium",
            f"No medical tests at purchase for your ages. Declare every condition, medicine and past test. "
            f"For the first {mor:g} months the insurer can reject a claim for non-disclosure."))

    # Co-pays.
    if (cp := v("general_copay_pct")):
        g.append(Gotcha("high", f"{cp}% co-pay on every claim: you pay {inr(cp / 100 * 500000)} of a Rs 5L bill."))
    age_cp, cp_from = v("age_copay_pct"), v("age_copay_from_age")
    if age_cp and cp_from:
        for m in user.members:
            if m.age >= cp_from:
                g.append(Gotcha("high", f"{m.name} ({m.age}) already falls under the {age_cp}% age co-pay (from {cp_from})."))
            elif m.age + 5 >= cp_from:
                g.append(Gotcha("medium", f"{m.name} hits the {age_cp}% age co-pay at {cp_from}, {cp_from - m.age} years from now."))
    zcp = v("zone_copay_pct")
    if zcp and plan.zone and ZONE_COST_RANK[zone] > ZONE_COST_RANK[plan.zone]:
        g.append(Gotcha("high", f"Plan priced for Zone {plan.zone}, but {user.city} is Zone {zone}: {zcp}% co-pay "
                                 f"on claims there. Buy Zone {zone} pricing or accept the co-pay."))
    if (ded := v("deductible_amount")):
        g.append(Gotcha("medium", f"First {inr(ded)} of claims is yours (deductible)."))
    if (nn := v("non_network_copay_pct")):
        g.append(Gotcha("medium", f"{nn}% co-pay if treated outside the network."))

    # Sub-limits and exclusions.
    if v("disease_sublimits") not in (None, "none"):
        g.append(Gotcha("high", f"Disease-wise sub-limits apply ({v('disease_sublimits').replace('_', ' ')}). Common "
                                 "surgeries pay a fixed amount, whatever your sum insured."))
    if (ns := v("notable_sublimits")):
        g.append(Gotcha("medium", f"Cap found in the wording: {ns}."))
    if (cat := v("cataract_limit")) and user.oldest >= 50 and cat < 100000:
        g.append(Gotcha("medium", f"Cataract paid up to only {inr(cat)} per eye; premium lenses in a private hospital cost more."))
    mt = v("modern_treatment_limit_pct")
    if isinstance(mt, (int, float)) and mt < 100:
        g.append(Gotcha("medium", f"Robotic surgery, immunotherapy, oral chemo etc. capped at {mt}% of SI ({inr(plan.sum_insured * mt / 100)})."))
    if v("consumables_covered") is False:
        g.append(Gotcha("medium", "Consumables (gloves, PPE, kits, belts) are not paid. Expect 5-15% of the bill out of pocket."
                                   + _note(plan, "consumables_covered")))
    if v("min_hospitalisation_hrs") == 24 and v("day_care_all") is False:
        g.append(Gotcha("info", "Stays under 24h are paid only for listed day-care procedures."))
    if v("investigation_only_excluded"):
        g.append(Gotcha("info", "Admissions only for tests are rejected. Make sure the discharge summary records active treatment."))

    # Sum insured mechanics.
    if v("restoration_type") == "once_unrelated_only":
        g.append(Gotcha("medium", "Restoration works only for an unrelated illness. A relapse of the same illness in the same year is not covered by it."))
    if v("ncb_reduces_on_claim"):
        g.append(Gotcha("info", "No-claim bonus drops after a claim; do not count it as permanent cover."))

    # Hospitals.
    for h in user.preferred_hospitals:
        if h in plan.excluded_hospitals:
            g.append(Gotcha("high", f"{h} is on this insurer's EXCLUDED list: claims there are not paid except in emergencies."))
        elif h not in plan.network_hospitals:
            g.append(Gotcha("medium", f"{h} is not in network: reimbursement only (pay first, claim later)."))

    # Maternity.
    if user.planning_pregnancy:
        if not v("maternity_covered"):
            g.append(Gotcha("high", "Maternity is not covered."))
        elif (mw := v("maternity_waiting_months")):
            g.append(Gotcha("medium", f"Maternity claimable only after {mw:g} months; plan a pregnancy after that."))

    # Family structure, a common Indian mistake.
    parents = [m for m in user.members if m.is_parent]
    if parents and len(parents) < len(user.members):
        g.append(Gotcha("medium", "Parents on the same floater raise the premium (it is priced on the eldest) and use up "
                                   "the shared sum insured. A separate policy for parents is usually better."))

    # Over-reliance on employer cover.
    if user.employer_cover and plan.sum_insured < 10_00_000:
        g.append(Gotcha("info", f"Employer cover ({inr(user.employer_cover)}) ends with the job, and waiting periods "
                                 "restart on a new policy. Keep a personal base plan anyway."))
    return g


# --------------------------------------------------------------------------- claim simulator

@dataclass
class ClaimScenario:
    bill: int
    room_rent_per_day: int
    days: int
    patient_age: int
    procedure: str = ""  # e.g. "cataract" to apply sub-limits
    network: bool = True
    consumables_share: float = 0.08  # share of bill that is IRDAI non-payables
    unaffected_share: float = 0.30  # medicines, implants, diagnostics: exempt from proportionate deduction


def simulate_claim(plan: Plan, s: ClaimScenario, user: UserProfile) -> tuple[int, list[tuple[str, int]]]:
    """Estimate the payout and itemised deductions for one hospitalisation.
    Unknown terms are treated as not applying, so this is a best case."""
    plan = with_derived(plan, user.sum_insured)
    v = plan.get
    steps: list[tuple[str, int]] = []
    payable = float(s.bill)

    if v("consumables_covered") is False:
        cut = s.bill * s.consumables_share
        steps.append(("Consumables / non-payables", round(cut)))
        payable -= cut

    room = v("room_rent_limit")
    if room in ROOM_CAP_PCT:
        cap = plan.sum_insured * ROOM_CAP_PCT[room] / 100
        if s.room_rent_per_day > cap:
            excess_room = (s.room_rent_per_day - cap) * s.days
            steps.append(("Room rent above cap", round(excess_room)))
            payable -= excess_room
            if v("proportionate_deduction"):
                room_total = s.room_rent_per_day * s.days
                associated = max(0.0, s.bill * (1 - s.unaffected_share - s.consumables_share) - room_total)
                cut = associated * (1 - cap / s.room_rent_per_day)
                steps.append((f"Proportionate deduction ({cap / s.room_rent_per_day:.0%} paid)", round(cut)))
                payable -= cut

    if s.procedure == "cataract" and (lim := v("cataract_limit")) and payable > lim:
        steps.append(("Cataract sub-limit", round(payable - lim)))
        payable = lim

    copay = v("general_copay_pct") or 0
    if (acp := v("age_copay_pct")) and s.patient_age >= (v("age_copay_from_age") or 999):
        copay += acp
    zone = user.zone_for(plan)
    if plan.zone and ZONE_COST_RANK[zone] > ZONE_COST_RANK[plan.zone]:
        copay += v("zone_copay_pct") or 0
    if not s.network:
        copay += v("non_network_copay_pct") or 0
    if copay:
        cut = payable * copay / 100
        steps.append((f"Co-pay {copay}%", round(cut)))
        payable -= cut

    if (ded := v("deductible_amount")):
        cut = min(ded, payable)
        steps.append(("Deductible", round(cut)))
        payable -= cut

    if payable > plan.sum_insured:
        steps.append(("Above sum insured", round(payable - plan.sum_insured)))
        payable = plan.sum_insured
    return round(max(payable, 0)), steps

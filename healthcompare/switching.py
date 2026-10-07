"""Switching analysis (audience C): what someone with an existing policy gains, loses
or restarts by moving to another plan, or by staying and upgrading.

Portability rules live in PORTABILITY below, each with its source. Anything not
yet confirmed from IRDAI's own documents is marked `verified: False` and is
worded cautiously wherever it is shown.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .criteria import BY_ID
from .engine import approx_premium, table_premium, with_derived
from .explain import show, source_of
from .india import IRDAI_MORATORIUM_MONTHS, inr
from .models import CitedValue, CurrentPolicy, Plan, UserProfile

# Portability rules. Filled from IRDAI sources; see docs/DESIGN.md.
PORTABILITY: dict[str, dict] = {
    "waiting_credit": {"verified": False, "source": "",
                       "text": "Waiting periods already served count toward the new plan's waiting periods, up to your old sum insured."},
    "increase_fresh_wait": {"verified": False, "source": "",
                            "text": "Any increase in sum insured carries fresh waiting periods on the increased part."},
    "credit_includes_bonus": {"verified": False, "source": "",
                              "text": "Accrued bonus may count as part of the sum insured that gets waiting-period credit."},
    "moratorium_continues": {"verified": False, "source": "",
                             "text": "Continuous cover with the previous insurer counts toward the 5-year moratorium."},
    "apply_window": {"verified": False, "source": "", "text": "Apply to the new insurer before your renewal date."},
    "underwriting": {"verified": False, "source": "",
                     "text": "The new insurer can underwrite afresh: it may accept, load the premium, or decline."},
    "keep_old_active": {"verified": False, "source": "",
                        "text": "Keep the old policy active (renew it if needed) until the new insurer issues the policy."},
}

# Terms compared between the current plan and each alternative.
COMPARE = ("room_rent_limit", "proportionate_deduction", "icu_limit", "general_copay_pct", "age_copay_pct",
           "zone_copay_pct", "disease_sublimits", "consumables_covered", "modern_treatment_limit_pct",
           "restoration_type", "ncb_pct_per_year", "ncb_reduces_on_claim", "pre_hosp_days", "post_hosp_days",
           "day_care_all", "domiciliary", "maternity_covered", "csr_count", "complaints_per_10k")
WAITS = (("initial_waiting_days", "Initial waiting period", 1 / 30),  # days -> months
         ("ped_waiting_months", "Pre-existing disease waiting", 1),
         ("specific_disease_waiting_months", "Specific-illness waiting", 1),
         ("maternity_waiting_months", "Maternity waiting", 1))


@dataclass
class SwitchItem:
    kind: str  # "gain" | "loss" | "wait" | "keeps" | "caution"
    text: str
    source: str = ""


@dataclass
class SwitchAnalysis:
    plan: Plan
    staying: bool  # the candidate is the user's current plan (stay, possibly upgrade cover)
    premium_now: int | None
    premium_new: int | None
    premium_new_basis: str
    items: list[SwitchItem] = field(default_factory=list)

    def by_kind(self, kind: str) -> list[SwitchItem]:
        return [i for i in self.items if i.kind == kind]


def current_plan(cp: CurrentPolicy, plans: list[Plan]) -> Plan:
    """The user's current plan: from our data if we have it, else built from what they told us."""
    known = next((p for p in plans if p.id == cp.plan_id), None)
    if known:
        return known
    vals = {cid: CitedValue(v, confidence=0.7, note="As you described your current policy")
            for cid, v in cp.terms.items() if cid in BY_ID}
    return Plan(id="current", insurer="Your current", name=cp.name or "policy", values=vals)


def _premium(plan: Plan, user: UserProfile) -> tuple[int | None, str]:
    if (tp := table_premium(plan, user)):
        return tp.amount, "insurer table"
    if (ap := approx_premium(plan, user)):
        return ap.estimate.best, "approx." + ("" if ap.close else ", different profile")
    return None, "get a quote"


def _wait_items(cand: Plan, cp: CurrentPolicy, user: UserProfile, staying: bool) -> list[SwitchItem]:
    """One line for waits already served, one for waits still running on existing cover,
    one for fresh waits on any extra cover."""
    served = cp.months_continuous
    credited = cp.sum_insured + (cp.cumulative_bonus if PORTABILITY["credit_includes_bonus"]["verified"] else 0)
    increase = max(0, user.sum_insured - credited)
    done, running, fresh = [], [], []
    for cid, label, to_months in WAITS:
        if (cid == "maternity_waiting_months" and not user.planning_pregnancy) or (cid == "ped_waiting_months" and not user.has_ped):
            continue
        wait = cand.get(cid)
        if not isinstance(wait, (int, float)) or wait == 0:
            continue
        months = wait * to_months
        span = f"{wait:g} days" if to_months != 1 else f"{wait:g} months"
        short = label.replace(" waiting", "").replace(" period", "")
        (done if months <= served else running).append(
            short if months <= served else f"{short} ({months - served:g} more months)")
        if increase:
            fresh.append(f"{short} {span}")
    out = []
    if done:
        out.append(SwitchItem("keeps", f"Waiting periods already served on your {inr(cp.sum_insured)} "
                                       f"({served} months of cover): {', '.join(done)}."))
    if running:
        out.append(SwitchItem("wait", f"Still to serve on your existing cover: {', '.join(running)}."))
    if fresh:
        out.append(SwitchItem("wait", f"The extra {inr(increase)} of cover starts fresh waits: {', '.join(fresh)}."))
    return out


def _compare_terms(cur: Plan, cand: Plan) -> list[SwitchItem]:
    out = []
    for cid in COMPARE:
        a, b = cur.values.get(cid), cand.values.get(cid)
        if not a or not b:
            continue
        crit = BY_ID[cid]
        sa, sb = crit.score(a.value), crit.score(b.value)
        if sa is None or sb is None or abs(sb - sa) < 0.2:
            continue
        kind = "gain" if sb > sa else "loss"
        out.append(SwitchItem(kind, f"{crit.label}: {show(cid, a.value)} now, {show(cid, b.value)} with this plan",
                              source_of(b)))
    return out


def analyse(cand_plan: Plan, cp: CurrentPolicy, plans: list[Plan], user: UserProfile) -> SwitchAnalysis:
    cur_raw = current_plan(cp, plans)
    staying = cand_plan.id == cur_raw.id
    cur = with_derived(cur_raw, cp.sum_insured)
    cand = with_derived(cand_plan, user.sum_insured)

    now = cp.annual_premium
    if now is None and cur_raw.id != "current":
        now = _premium(cur_raw, replace(user, sum_insured=cp.sum_insured))[0]
    new, basis = _premium(cand_plan, user)
    a = SwitchAnalysis(cand_plan, staying, now, new, basis)

    if staying:
        if user.sum_insured > cp.sum_insured:
            a.items.append(SwitchItem("gain", f"Raise cover from {inr(cp.sum_insured)} to {inr(user.sum_insured)} "
                                              f"at renewal with the same insurer: no switching paperwork."))
        a.items += _compare_terms(cur, cand)  # terms that change with the higher cover
    else:
        a.items += _compare_terms(cur, cand)
        if cur.get("premium_age_lock") and not cand.get("premium_age_lock"):
            a.items.append(SwitchItem("loss", "You lose your locked entry-age premium (premium would follow your "
                                              "current age band with the new insurer).", source_of(cur.values.get("premium_age_lock"))))
        if cp.cumulative_bonus:
            a.items.append(SwitchItem("caution", f"Your accrued bonus of {inr(cp.cumulative_bonus)}: "
                                                 f"{PORTABILITY['credit_includes_bonus']['text']}"))
    a.items += _wait_items(cand, cp, user, staying)

    left = max(0, IRDAI_MORATORIUM_MONTHS - cp.months_continuous)
    mor = (f"5-year moratorium: {'complete' if not left else f'{left} months to go'} "
           f"(after it, a claim can't be rejected for non-disclosure, except fraud).")
    if staying or PORTABILITY["moratorium_continues"]["verified"]:
        a.items.append(SwitchItem("keeps", mor))
    else:
        a.items.append(SwitchItem("caution", mor + " " + PORTABILITY["moratorium_continues"]["text"]))

    if not staying:
        for key in ("apply_window", "underwriting", "keep_old_active"):
            a.items.append(SwitchItem("caution", PORTABILITY[key]["text"], PORTABILITY[key]["source"]))
        if cp.claimed_last_year or not cp.conditions_declared:
            a.items.append(SwitchItem("caution", "Declare every condition and past claim on the new proposal form; "
                                                 "non-disclosure is the most common reason claims are rejected."))
    return a

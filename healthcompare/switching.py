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

# Portability rules, each confirmed against IRDAI's own documents (full list with
# quotes: data/india/portability_rules.json).
PPI = "IRDAI Policyholders' Interests Master Circular 2024"  # irdai.gov.in/document-detail?documentId=5625747
HMC = "IRDAI Health Master Circular 2024"  # irdai.gov.in/document-detail?documentId=4942918
PRR = "IRDAI Products Regulations 2024, Sch. III"  # irdai.gov.in/document-detail?documentId=4590475
PORTABILITY: dict[str, dict] = {
    "waiting_credit": {"verified": True, "source": PPI + " 24.6",
        "text": "Credits for waiting periods (pre-existing disease, specific illnesses) and the moratorium carry over to the "
                "new insurer, up to your old sum insured plus accrued no-claim bonus."},
    "credit_includes_bonus": {"verified": True, "source": PPI + " 24.6",
        "text": "Your accrued bonus counts toward the cover that gets waiting-period credit, but the new insurer is not "
                "required to keep it as free extra cover: check how it will show on the new policy."},
    "increase_fresh_wait": {"verified": True, "source": HMC + ", CIS template",
        "text": "Any increase in sum insured restarts waiting periods on the increased part only."},
    "moratorium_continues": {"verified": True, "source": PRR + " para 8",
        "text": "Continuous cover with your old insurer counts toward the 5-year moratorium; on any increased cover the "
                "5 years start again for the increased amount only."},
    "apply_window": {"verified": True, "source": PPI + " 24.2",
        "text": "Apply to the new insurer 30 to 60 days before your renewal date. Later than that, the insurer may still "
                "accept but doesn't have to."},
    "entire_family": {"verified": True, "source": PPI + " 24.2",
        "text": "Port the whole policy with every family member on it."},
    "underwriting": {"verified": True, "source": PRR + " para 10.2; " + PPI + " 24.5",
        "text": "The new insurer underwrites you afresh: it may accept, add a premium loading or decline. It must decide "
                "within 5 days of getting your records from the old insurer (which has 72 hours to send them)."},
    "no_charges": {"verified": True, "source": PPI + " 24.7", "text": "Porting is free: neither insurer may charge you for it."},
    "keep_old_active": {"verified": True, "source": HMC + " para 8; " + PRR + " para 1.2",
        "text": "Don't let the old policy lapse while the port is pending. You can renew within the 30-day grace period "
                "without losing credits, but there is no cover during that grace period."},
    "free_look": {"verified": True, "source": "insurer wordings (e.g. HDFC ERGO Optima Secure 1.8)",
        "text": "The free-look cancellation period does not apply to a ported policy."},
    "new_benefit_fresh_wait": {"verified": True, "source": PRR + " para 10.2 (credit only for benefits in the previous policy)",
        "text": "A benefit your old policy didn't have (e.g. maternity) starts its full waiting period."},
    "renewal_underwriting": {"verified": True, "source": HMC + " para 10(c)",
        "text": "Renewing with the same insurer: no fresh underwriting, except on any increase in sum insured."},
    "migration": {"verified": True, "source": PRR + " para 10.1",
        "text": "Moving to another plan of the same insurer (migration) keeps your credits; the insurer may underwrite only "
                "if you have had less than 36 months of continuous cover."},
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


def extra_cover(cp: CurrentPolicy, user: UserProfile, staying: bool) -> int:
    """Cover that is new and so starts fresh waits and a fresh moratorium. Staying: the increase in base sum
    insured (CIS template). Porting: anything above old sum insured plus accrued bonus (PPI MC 24.6)."""
    base = cp.sum_insured if staying else cp.sum_insured + cp.cumulative_bonus
    return max(0, user.sum_insured - base)


def _wait_items(cand: Plan, cp: CurrentPolicy, user: UserProfile, staying: bool, cur: Plan | None = None) -> list[SwitchItem]:
    """One line for waits already served, one for waits still running on existing cover,
    one for fresh waits on any extra cover."""
    served = cp.months_continuous
    increase = extra_cover(cp, user, staying)
    done, running, fresh = [], [], []
    for cid, label, to_months in WAITS:
        if (cid == "maternity_waiting_months" and not user.planning_pregnancy) or (cid == "ped_waiting_months" and not user.has_ped):
            continue
        wait = cand.get(cid)
        if not isinstance(wait, (int, float)) or wait == 0:
            continue
        months = wait * to_months
        span = f"{wait:g} days" if to_months != 1 else f"{wait:g} months"
        if cid == "maternity_waiting_months" and cur is not None and cur.get("maternity_covered") is not True:
            running.append(f"Maternity ({months:g} months, not covered by your current plan so no credit)")
            continue
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
        if cp.cumulative_bonus and cand_plan.insurer_id != cur_raw.insurer_id:
            a.items.append(SwitchItem("caution", f"Your accrued bonus of {inr(cp.cumulative_bonus)}: "
                                                 f"{PORTABILITY['credit_includes_bonus']['text']}",
                                      PORTABILITY["credit_includes_bonus"]["source"]))
    a.items += _wait_items(cand, cp, user, staying, cur)

    left = max(0, IRDAI_MORATORIUM_MONTHS - cp.months_continuous)
    a.items.append(SwitchItem("keeps", f"5-year moratorium on your existing cover: "
                                       f"{'complete' if not left else f'{left} months to go'} (after it, a claim can't be "
                                       f"rejected for non-disclosure, except fraud)."))
    extra = extra_cover(cp, user, staying)
    if extra:
        a.items.append(SwitchItem("wait", f"On the extra {inr(extra)}, the 5-year moratorium starts from zero.",
                                  PORTABILITY["moratorium_continues"]["source"]))

    migration = not staying and cur_raw.insurer_id and cand_plan.insurer_id == cur_raw.insurer_id
    if staying:
        a.items.append(SwitchItem("keeps", PORTABILITY["renewal_underwriting"]["text"], PORTABILITY["renewal_underwriting"]["source"]))
    elif migration:
        a.items.append(SwitchItem("keeps", "Same insurer, different plan (migration): " + PORTABILITY["migration"]["text"]
                                  + (" You have 36+ months, so no fresh underwriting." if cp.months_continuous >= 36 else ""),
                                  PORTABILITY["migration"]["source"]))
    else:
        for key in ("apply_window", "entire_family", "underwriting", "no_charges", "keep_old_active", "free_look"):
            a.items.append(SwitchItem("caution", PORTABILITY[key]["text"], PORTABILITY[key]["source"]))
        if cp.claimed_last_year or not cp.conditions_declared:
            a.items.append(SwitchItem("caution", "Declare every condition and past claim on the new proposal form; "
                                                 "non-disclosure is the most common reason claims are rejected."))
    return a

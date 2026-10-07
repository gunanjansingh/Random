"""Switching analysis (audience C): what someone with an existing policy gains, loses
or restarts by moving to another plan, or by staying and upgrading.

Every rule shown to users is in PORTABILITY with its source; the full verified set
(with quotes) is data/india/portability_rules.json.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .criteria import BY_ID
from .engine import approx_premium, table_premium, with_derived
from .explain import show, source_of
from .india import IRDAI_MORATORIUM_MONTHS, inr
from .models import CitedValue, CurrentPolicy, Plan, UserProfile

PPI = "IRDAI Policyholders' Interests Master Circular 2024"  # irdai.gov.in/document-detail?documentId=5625747
HMC = "IRDAI Health Master Circular 2024"  # irdai.gov.in/document-detail?documentId=4942918
PRR = "IRDAI Products Regulations 2024, Sch. III"  # irdai.gov.in/document-detail?documentId=4590475
INITIAL_WAIT_WAIVED_AFTER_MONTHS = 12  # standard wording Excl03: no 30-day wait after >12 months' continuous cover

PORTABILITY: dict[str, dict] = {
    "waiting_credit": {"source": PPI + " 24.6",
        "text": "Credits for waiting periods (pre-existing disease, specific illnesses) and the moratorium carry over to the "
                "new insurer, up to your old sum insured plus accrued no-claim bonus."},
    "credit_includes_bonus": {"source": PPI + " 24.6",
        "text": "Your accrued no-claim bonus should count toward the cover that gets waiting-period credit, but the new "
                "insurer need not keep it as free extra cover, and loyalty or carry-forward boosters may not count as "
                "no-claim bonus. Get the credited amount confirmed in writing."},
    "increase_fresh_wait": {"source": HMC + ", CIS template",
        "text": "Any increase in sum insured restarts waiting periods on the increased part only."},
    "moratorium_continues": {"source": PRR + " para 8",
        "text": "Continuous cover counts toward the 5-year moratorium; on any increased cover the 5 years start again for "
                "the increased amount only."},
    "apply_window": {"source": PPI + " 24.2",
        "text": "Apply to the new insurer 30 to 60 days before your renewal date. Later than that, the insurer may still "
                "accept but doesn't have to."},
    "entire_family": {"source": PPI + " 24.2", "text": "Port the whole policy with every family member on it."},
    "underwriting": {"source": PRR + " para 10.2; " + PPI + " 24.5",
        "text": "The new insurer underwrites you afresh: it may accept, add a premium loading (which usually stays at every "
                "renewal), permanently exclude a declared condition, or decline. It must decide within 5 days of getting "
                "your records from the old insurer (which has 72 hours to send them). Read the offer's schedule before "
                "letting the old policy go."},
    "no_charges": {"source": PPI + " 24.7", "text": "Porting is free: neither insurer may charge you for it."},
    "keep_old_active": {"source": HMC + " para 8; " + PRR + " para 1.2",
        "text": "If the new policy isn't issued by your renewal date, renew the old one: don't let it lapse. Renewing "
                "within the grace period ({grace} days) keeps your credits, but there is usually no cover during it."},
    "free_look": {"source": "insurer wordings (e.g. HDFC ERGO Optima Secure 1.8, Star)",
        "text": "Many insurers give no free-look cancellation period on a ported policy: compare carefully before you port."},
    "disclosure": {"source": HMC + " paras 12(a), 13",
        "text": "The new proposal form is a fresh declaration and the new insurer sees your full claim history. Declare every "
                "condition (including any that started after you bought the old policy) and past claims: until the "
                "5-year moratorium is complete, a claim can be contested for non-disclosure."},
    "renewal_underwriting": {"source": HMC + " para 10(c)",
        "text": "Renewing with the same insurer: no fresh underwriting, except on any increase in sum insured."},
    "migration": {"source": PRR + " para 10.1",
        "text": "Moving to another plan of the same insurer (migration) keeps your credits up to your current cover. "
                "Many insurers ask for the request at least 30 days before renewal."},
    "group": {"source": PRR + " para 10.2",
        "text": "Leaving an employer or group policy: credits may be given, subject to the new insurer's underwriting. "
                "Apply before the group cover ends, and ask the group insurer about moving to its retail plan."},
}

COMPARE = ("room_rent_limit", "proportionate_deduction", "icu_limit", "general_copay_pct", "age_copay_pct",
           "zone_copay_pct", "disease_sublimits", "consumables_covered", "modern_treatment_limit_pct",
           "restoration_type", "ncb_pct_per_year", "ncb_reduces_on_claim", "pre_hosp_days", "post_hosp_days",
           "day_care_all", "domiciliary", "maternity_covered", "csr_count", "complaints_per_10k")


@dataclass
class SwitchItem:
    kind: str  # "gain" | "loss" | "wait" | "keeps" | "caution"
    text: str
    source: str = ""


@dataclass
class SwitchAnalysis:
    plan: Plan
    staying: bool
    migration: bool
    premium_now: int | None
    premium_now_basis: str
    premium_new: int | None
    premium_new_basis: str
    comparable_prices: bool  # both figures are for this family and these covers
    total_cover: str  # what the user would end up with
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
    return Plan(id="current", insurer="Your current", name=cp.name or "policy", values=vals, insurer_id=cp.insurer_id)


def _premium(plan: Plan, user: UserProfile) -> tuple[int | None, str, bool]:
    """(amount, basis, is it for this family at this cover)."""
    if (tp := table_premium(plan, user)):
        return tp.amount, "insurer table", True
    if (ap := approx_premium(plan, user)):
        e = ap.estimate
        return e.best, (f"approx., quoted for {e.members} aged {'/'.join(map(str, e.ages))} at {inr(e.sum_insured)}"
                        if not ap.close else "approx."), ap.close
    return None, "get a quote", False


def extra_cover(cp: CurrentPolicy, user: UserProfile, staying: bool) -> int:
    """Cover that is new and so starts fresh waits and a fresh moratorium. Staying: the increase in base sum
    insured (CIS template). Porting: anything above old sum insured plus accrued bonus (PPI MC 24.6)."""
    base = cp.sum_insured if staying else cp.sum_insured + cp.cumulative_bonus
    return max(0, user.sum_insured - base)


def _credited(cp: CurrentPolicy, staying: bool) -> str:
    if staying or not cp.cumulative_bonus:
        return inr(cp.sum_insured)
    return f"{inr(cp.sum_insured + cp.cumulative_bonus)} ({inr(cp.sum_insured)} cover + {inr(cp.cumulative_bonus)} bonus)"


def _wait_items(cand: Plan, cur: Plan, cp: CurrentPolicy, user: UserProfile, staying: bool) -> list[SwitchItem]:
    served = cp.months_continuous
    increase = extra_cover(cp, user, staying)
    done, running, fresh, unknown, out = [], [], [], [], []

    def track(label: str, months: float, span: str) -> None:
        if months <= served:
            done.append(label)
        else:
            running.append(f"{label} ({months - served:g} more months)")
        if increase:
            fresh.append(f"{label} {span}")

    # 30-day initial wait: the standard wording waives it only after more than 12 months' continuous cover.
    init = cand.get("initial_waiting_days")
    if isinstance(init, (int, float)) and init:
        if staying or served > INITIAL_WAIT_WAIVED_AFTER_MONTHS:
            done.append("Initial 30-day")
        else:
            running.append(f"Initial {init:g}-day (may apply again: you have {served} months of cover, the usual waiver "
                           f"needs more than {INITIAL_WAIT_WAIVED_AFTER_MONTHS})")
        if increase:
            fresh.append(f"Initial {init:g} days")

    if user.has_ped:
        ped = cand.get("ped_waiting_months")
        if not cp.conditions_declared:
            out.append(SwitchItem("loss", "An existing illness you did not declare is not covered, and until the 5-year "
                                          "moratorium is complete the insurer can void the policy or reject claims for it. "
                                          "Declare it to your current insurer now, whatever you decide.",
                                  HMC + " para 13; insurer wordings (e.g. Niva Bupa ReAssure 2.0)"))
        elif isinstance(ped, (int, float)):
            track("Pre-existing disease", ped, f"{ped:g} months")
        else:
            unknown.append("pre-existing disease")
    spec = cand.get("specific_disease_waiting_months")
    if isinstance(spec, (int, float)) and spec:
        track("Specific-illness", spec, f"{spec:g} months")
    elif spec is None:
        unknown.append("specific-illness")

    if user.planning_pregnancy:
        if cand.get("maternity_covered") is not True:
            out.append(SwitchItem("loss", "Maternity: " + ("not covered by this plan."
                                  if cand.get("maternity_covered") is False else "cover unknown: ask the insurer.")))
        else:
            mat = cand.get("maternity_waiting_months")
            if not isinstance(mat, (int, float)):
                unknown.append("maternity")
            elif cur.get("maternity_covered") is True:
                track("Maternity", mat, f"{mat:g} months")
            else:
                had = "isn't covered by your current plan" if cur.get("maternity_covered") is False else "may not be in your current plan"
                out.append(SwitchItem("wait", f"Maternity is new cover for you (it {had}), so the full {mat:g}-month wait "
                                              f"applies: a pregnancy in that time would not be covered."))

    who = "" if cp.all_members_since_start else " for members covered the whole time"
    if done:
        out.append(SwitchItem("keeps", f"Waiting periods already served on your {_credited(cp, staying)} "
                                       f"({served} months of cover{who}): {', '.join(done)}."))
    if running:
        out.append(SwitchItem("wait", f"Still to serve on your existing cover: {', '.join(running)}."))
    if fresh:
        out.append(SwitchItem("wait", f"The extra {inr(increase)} of cover starts fresh waits: {', '.join(fresh)}.",
                              PORTABILITY["increase_fresh_wait"]["source"]))
    if not cp.all_members_since_start:
        out.append(SwitchItem("caution", "Members who joined the policy later have less credit: their waits are counted "
                                         "from when they were added."))
    if unknown:
        out.append(SwitchItem("caution", f"Waiting period not known for this plan: {', '.join(unknown)}. Ask the insurer "
                                         f"how much credit you would get."))
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
        out.append(SwitchItem("gain" if sb > sa else "loss",
                              f"{crit.label}: {show(cid, a.value)} now, {show(cid, b.value)} with this plan", source_of(b)))
    return out


def analyse(cand_plan: Plan, cp: CurrentPolicy, plans: list[Plan], user: UserProfile) -> SwitchAnalysis:
    cur_raw = current_plan(cp, plans)
    staying = cand_plan.id == cur_raw.id
    migration = not staying and bool(cur_raw.insurer_id) and cand_plan.insurer_id == cur_raw.insurer_id
    cur = with_derived(cur_raw, cp.sum_insured)
    cand = with_derived(cand_plan, user.sum_insured)
    extra = extra_cover(cp, user, staying)

    if cp.annual_premium is not None:
        now, now_basis, now_ok = cp.annual_premium, "what you pay", True
    elif cur_raw.id != "current":
        now, now_basis, now_ok = _premium(cur_raw, replace(user, sum_insured=cp.sum_insured))
        now_basis = "estimated: " + now_basis
    else:
        now, now_basis, now_ok = None, "not given", False
    new, new_basis, new_ok = _premium(cand_plan, user)
    if staying:
        total = f"{inr(user.sum_insured)} + your {inr(cp.cumulative_bonus)} bonus" if cp.cumulative_bonus else inr(user.sum_insured)
    else:
        total = inr(user.sum_insured) + (" (your bonus may or may not be kept on top)" if cp.cumulative_bonus else "")
    a = SwitchAnalysis(cand_plan, staying, migration, now, now_basis, new, new_basis, now_ok and new_ok, total)

    if staying:
        offered = cand_plan.sum_insured_options
        if user.sum_insured > cp.sum_insured and offered and user.sum_insured not in offered:
            a.items.append(SwitchItem("loss", f"Your plan isn't sold at {inr(user.sum_insured)} (options: "
                                              f"{', '.join(inr(x) for x in offered)}): staying means keeping a lower cover "
                                              f"or moving to another plan of this insurer."))
        elif user.sum_insured > cp.sum_insured:
            a.items.append(SwitchItem("gain", f"Raise cover from {inr(cp.sum_insured)} to {inr(user.sum_insured)} at "
                                              f"renewal with the same insurer: no switching paperwork."))
        a.items += _compare_terms(cur, cand)  # terms that change with the higher cover
    else:
        a.items += _compare_terms(cur, cand)
        if cur.get("premium_age_lock") and not cand.get("premium_age_lock") and not cp.ever_claimed:
            a.items.append(SwitchItem("loss", "You would likely lose your locked entry-age premium (it lasts until a claim "
                                              "is paid; the new premium follows your current age band).",
                                      source_of(cur.values.get("premium_age_lock"))))
        if cp.cumulative_bonus and not migration:
            a.items.append(SwitchItem("caution", f"Your accrued bonus of {inr(cp.cumulative_bonus)}: "
                                                 f"{PORTABILITY['credit_includes_bonus']['text']}",
                                      PORTABILITY["credit_includes_bonus"]["source"]))
    a.items += _wait_items(cand, cur, cp, user, staying)

    left = max(0, IRDAI_MORATORIUM_MONTHS - cp.months_continuous)
    if cp.conditions_declared:
        a.items.append(SwitchItem("keeps", f"5-year moratorium on your existing cover: "
                                           f"{'complete' if not left else f'{left} months to go'} (after it, a claim can't "
                                           f"be rejected for non-disclosure, except fraud)."))
    if extra:
        a.items.append(SwitchItem("wait", f"On the extra {inr(extra)}, the 5-year moratorium starts from zero.",
                                  PORTABILITY["moratorium_continues"]["source"]))

    if staying:
        a.items.append(SwitchItem("keeps", PORTABILITY["renewal_underwriting"]["text"],
                                  PORTABILITY["renewal_underwriting"]["source"]))
    elif migration:
        uw = (f"Your existing cover is not re-underwritten (36+ months of continuous cover)"
              if cp.months_continuous >= 36 else "With under 36 months of cover the insurer may underwrite you again")
        uw += f"; the extra {inr(extra)} may be underwritten (medicals, loading or decline)." if extra else "."
        a.items.append(SwitchItem("keeps", f"Same insurer, different plan (migration). {PORTABILITY['migration']['text']} {uw}",
                                  PORTABILITY["migration"]["source"]))
    else:
        keys = ["group"] if cp.employer_group else ["apply_window", "entire_family"]
        keys += ["underwriting", "no_charges", "keep_old_active", "free_look"]
        if left or user.has_ped or cp.claimed_last_year:
            keys.append("disclosure")
        for key in keys:
            text = PORTABILITY[key]["text"].replace("{grace}", "15" if cp.pays_monthly else "30")
            a.items.append(SwitchItem("caution", text, PORTABILITY[key]["source"]))
    return a


def porting_window(cp: CurrentPolicy) -> str | None:
    d = cp.renewal_in_days
    if d is None or cp.employer_group:
        return None
    grace = 15 if cp.pays_monthly else 30
    if d < 0:
        if -d <= grace:
            return (f"Your renewal date passed {-d} days ago. Renew within the {grace}-day grace period to keep all credits "
                    f"(no cover until you do); after that the credits are lost. Port at the next renewal.")
        return "Your renewal date has passed the grace period: the policy has lapsed and its credits are likely lost."
    if d > 60:
        return f"Porting window: opens in {d - 60} days and closes in {d - 30} days (30-60 days before renewal)."
    if d >= 30:
        return f"Porting window: open now, closes in {d - 30} days (apply at least 30 days before renewal)."
    return (f"Porting window: closed ({d} days to renewal). A new insurer may still accept, but doesn't have to; "
            f"otherwise renew and port at the next renewal. Moving to another plan of your current insurer may still be "
            f"possible, but many insurers ask for 30 days' notice: check with yours now.")

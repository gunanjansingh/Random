"""Ask the user's criteria, then compare the top contenders.

    python -m healthcompare            # interactive questionnaire
    python -m healthcompare --demo     # canned profile
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import india
from .criteria import BY_ID, Category
from .engine import ClaimScenario, ScoreCard, common_reference, rank, simulate_claim
from .explain import explain, headline
from .india import inr
from .models import CurrentPolicy, DealBreakers, Member, UserProfile, load_insurers, load_plans
from .switching import analyse, current_plan, porting_window

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "india"

KEY_ROWS = (
    "room_rent_limit", "proportionate_deduction", "general_copay_pct", "age_copay_pct", "zone_copay_pct",
    "disease_sublimits", "consumables_covered", "modern_treatment_limit_pct", "ped_waiting_months",
    "specific_disease_waiting_months", "maternity_covered", "restoration_type", "ncb_pct_per_year",
    "csr_count", "icr", "complaints_per_10k", "pre_hosp_days", "post_hosp_days",
)


def ask(prompt: str, default: str = "") -> str:
    ans = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return ans or default


def yes(prompt: str, default: bool = False) -> bool:
    return ask(prompt + " (y/n)", "y" if default else "n").lower().startswith("y")


def ask_number(prompt: str, default: str = "", minimum: float = 0, maximum: float | None = None) -> float:
    """Ask until the answer is a number in range; accepts '14,000', 'Rs 5', '20%'."""
    while True:
        raw = ask(prompt, default).lower().replace(",", "").replace("rs", "").replace("\u20b9", "").replace("%", "").strip()
        try:
            val = float(raw)
            if val >= minimum and (maximum is None or val <= maximum):
                return val
        except ValueError:
            pass
        print(f"  Please enter a number{f' between {minimum:g} and {maximum:g}' if maximum is not None else ''}.")


def ask_current_policy(plans, insurers=None) -> CurrentPolicy | None:
    if not yes("\nDo you already have a health policy you might switch or upgrade?"):
        return None
    print("Which plan is it?")
    for i, p in enumerate(plans, 1):
        print(f"  {i}. {p.label()}")
    print("  0. Another plan")
    pick = int(ask_number("Number", "0", 0, len(plans)))
    cp = CurrentPolicy(plan_id=plans[pick - 1].id if pick else None)
    if not pick:
        cp.name = ask("Its name (insurer and plan)")
        ins = sorted(insurers or {}, key=str)
        if ins:
            print("Which insurer?")
            for i, iid in enumerate(ins, 1):
                print(f"  {i}. {insurers[iid].name}")
            print("  0. Another insurer")
            k = int(ask_number("Number", "0", 0, len(ins)))
            cp.insurer_id = ins[k - 1] if k else ""
        cp.employer_group = yes("Is it an employer or group policy?")
        room = ask("Room rent limit: none / single (single private room) / 1% (1% of cover per day) / unknown", "unknown")
        room = room.lower().replace("%", "pct").replace(" ", "")
        room = {"1": "1pct", "1pct": "1pct", "no": "none", "nolimit": "none"}.get(room, room)
        if room in ("none", "single", "1pct"):
            cp.terms["room_rent_limit"] = {"none": "no_limit", "single": "single_private_room", "1pct": "1pct_si_per_day"}[room]
            cp.terms["proportionate_deduction"] = room != "none"
        copay = ask("Co-pay on every claim, in % (blank if unknown)").replace("%", "").strip()
        if copay:
            try:
                cp.terms["general_copay_pct"] = float(copay)
            except ValueError:
                pass
        for cid, q in (("consumables_covered", "Are consumables (gloves, PPE, kits) covered?"),
                       ("maternity_covered", "Does it cover maternity?")):
            ans = ask(f"{q} y/n/unknown", "unknown").lower()
            if ans in ("y", "yes", "n", "no"):
                cp.terms[cid] = ans.startswith("y")
    cp.sum_insured = int(ask_number("Its sum insured, in lakhs", "5", 0.5) * 1_00_000)
    cp.cumulative_bonus = int(ask_number("Bonus cover built up so far, in lakhs (0 if none)", "0", 0) * 1_00_000)
    cp.continuous_years = ask_number("Years of unbroken cover (including any earlier insurer you ported from)", "1", 0, 80)
    cp.all_members_since_start = yes("Has everyone on the policy been covered for all of that time?", True)
    prem = ask("What you pay per year now, in rupees (blank to skip)").replace(",", "").replace("Rs", "").strip()
    cp.annual_premium = int(float(prem)) if prem.replace(".", "", 1).isdigit() else None
    cp.pays_monthly = yes("Do you pay the premium monthly?")
    days = ask("Days until its renewal date (negative if it has passed; blank if unsure)").strip()
    cp.renewal_in_days = int(days) if days.lstrip("-").isdigit() else None
    cp.claimed_last_year = yes("Did you claim in the last policy year?")
    cp.ever_claimed = cp.claimed_last_year or yes("Has any claim ever been paid on it?")
    cp.conditions_declared = yes("Were all existing illnesses declared when you bought it?", True)
    return cp


def questionnaire(plans=(), insurers=None) -> UserProfile:
    print("\nWho should be covered? Enter one person per line as name,age (blank line to finish).")
    members: list[Member] = []
    while True:
        line = input("  member: ").strip()
        if not line:
            break
        name, age = [x.strip() for x in line.split(",")]
        conds = ask(f"  {name}: existing conditions (e.g. diabetes, hypertension, thyroid; blank if none)")
        members.append(Member(
            name, int(age),
            conditions=[c.strip() for c in conds.split(",") if c.strip()],
            planning_pregnancy=yes(f"  {name}: planning a pregnancy in the next 3 years?"),
            is_parent=yes(f"  {name}: is this your parent?"),
        ))
    if not members:
        members = [Member("You", 32)]

    city = ask("City where you'd most likely be treated", "Mumbai")
    si = int(float(ask("Sum insured you want, in lakhs", "10")) * 1_00_000)
    hospitals = [h.strip() for h in ask("Preferred hospitals (comma separated, optional)").split(",") if h.strip()]
    employer = int(ask("Employer group cover in rupees (0 if none)", "0"))
    budget = ask("Max annual premium in rupees (blank = no limit)")
    old_regime = yes("Do you file under the OLD tax regime (needed for the 80D deduction)?")

    print("\nDeal-breakers: plans failing any of these are dropped.")
    db = DealBreakers(
        no_room_rent_cap=yes("  Must have NO room-rent cap?", True),
        no_copay=yes("  Must have NO co-pay?", True),
        no_disease_sublimits=yes("  Must have NO disease-wise sub-limits?"),
        need_maternity=any(m.planning_pregnancy for m in members) and yes("  Maternity cover required?", True),
        preferred_hospitals_cashless=bool(hospitals) and yes("  Preferred hospitals must be cashless?", True),
        max_premium=int(budget) if budget else None,
    )
    if any(m.conditions for m in members):
        db.max_ped_wait_months = int(ask("  Max acceptable pre-existing disease waiting (months)", "36"))

    print("\nHow much do you care about each area? 0 = ignore .. 5 = critical.")
    priorities = {cat: int(ask(f"  {cat.value}", "3")) for cat in Category}
    return UserProfile(members, city=city, sum_insured=si, preferred_hospitals=hospitals, priorities=priorities,
                       deal_breakers=db, employer_cover=employer, old_tax_regime=old_regime,
                       current_policy=ask_current_policy(list(plans), insurers))


def demo_profile() -> UserProfile:
    return UserProfile(
        members=[Member("You", 34, conditions=["hypertension"]), Member("Spouse", 32)],
        city="Mumbai",
        sum_insured=10_00_000,
        deal_breakers=DealBreakers(no_room_rent_cap=True, max_ped_wait_months=36),
        employer_cover=5_00_000,
        old_tax_regime=True,
    )


def demo_switch_profile() -> UserProfile:
    """A couple with a 4-year-old Bajaj Health Guard Gold policy at Rs 5L, wanting Rs 10L and no room cap."""
    u = demo_profile()
    u.current_policy = CurrentPolicy(plan_id="bajaj-health-guard-gold", sum_insured=5_00_000, cumulative_bonus=1_00_000,
                                     continuous_years=4, annual_premium=None, claimed_last_year=False, renewal_in_days=50)
    return u


def switching_report(fit: list[ScoreCard], user: UserProfile, plans: list, top: int) -> None:
    cp = user.current_policy
    cur = current_plan(cp, plans)
    kind = "employer/group policy" if cp.employer_group else f"{cp.continuous_years:g} years of continuous cover"
    print(f"\n=== Stay or switch? You have {cur.label()}, {inr(cp.sum_insured)} cover"
          f"{f' + {inr(cp.cumulative_bonus)} bonus' if cp.cumulative_bonus else ''}, {kind} ===")
    if (w := porting_window(cp)):
        print(w)
    shown = [c.plan for c in fit[:top]]
    options = ([] if any(p.id == cur.id for p in shown) else [cur]) + shown
    marks = {"gain": "+ Better", "loss": "- Worse", "wait": "~ Waiting", "keeps": "= Keeps", "caution": "! Note"}
    cautions: list[str] = []
    for p in options:
        a = analyse(p, cp, plans, user)
        rank = next((i + 1 for i, c in enumerate(fit) if c.plan.id == p.id), None)
        where = f"#{rank} of {len(fit)} that fit" if rank else (
            "your current plan" if p.id == "current" else "does not fit your filters at this cover")
        raise_to = f" and raise cover to {inr(user.sum_insured)}" if user.sum_insured > cp.sum_insured else ""
        head = (f"Stay with {p.label()}{raise_to}" if a.staying else
                f"Move to {p.label()} (same insurer)" if a.migration else f"Switch to {p.label()}")
        now = f"{inr(a.premium_now)} ({a.premium_now_basis})" if a.premium_now else "now: not known"
        new = f"{inr(a.premium_new)} ({a.premium_new_basis})" if a.premium_new else "get a quote"
        price = f"premium {now} -> {new}" if a.comparable_prices else f"premium now {now}; new {new}"
        print(f"\n{head}  [{where}; cover {a.total_cover}; {price}]")
        if not a.staying and a.premium_new:
            print("  (New-insurer prices are before any underwriting loading.)")
        for k in ("gain", "loss", "wait", "keeps"):
            for item in a.by_kind(k):
                print(f"  {marks[k]}: {item.text}{f'  [{item.source}]' if item.source else ''}")
        cautions += [i.text for i in a.by_kind("caution") if i.text not in cautions]
    if cautions:
        print("\nBefore you switch:")
        for t in cautions:
            print(f"  ! {t}")
    print("  (Rules from IRDAI's 2024 master circulars and product regulations; sources in data/india/portability_rules.json.)")


def fmt(cid: str, value: object, confidence: float = 1.0) -> str:
    if value is None:
        return "? unknown"
    return _fmt(cid, value) + ("" if confidence >= 0.5 else " ~")


def _fmt(cid: str, value: object) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, str):
        return value.replace("_", " ")
    unit = BY_ID[cid].unit
    if unit == "Rs":
        return inr(value)
    return f"{value:g}{'%' if unit.startswith('%') else ' ' + unit if unit else ''}"


def premium_cell(c: ScoreCard) -> str:
    if c.priced is not None:
        return f"{inr(c.priced.amount)} (insurer table)"
    if c.premium is not None:
        return inr(c.premium)
    if c.approx:
        return f"~{inr(c.approx.estimate.best)}" + ("" if c.approx.close else " (diff. profile)")
    return "get quote"


def table(rows: list[list[str]]) -> str:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    widths = [min(w, 34) for w in widths]
    lines = []
    for n, r in enumerate(rows):
        lines.append("  ".join(cell[:widths[i]].ljust(widths[i]) for i, cell in enumerate(r)))
        if n == 0:
            lines.append("  ".join("-" * w for w in widths))
    return "\n".join(lines)


def report(fit: list[ScoreCard], rejected: list[ScoreCard], user: UserProfile, top: int = 3, plans: list | None = None) -> None:
    """`fit`: every plan that passed the filters, best first; the first `top` are explained."""
    cards = fit[:top]
    if not cards:
        print("\nNo plan passes all your filters. Relax one and retry:")
        for c in rejected:
            print(f"  x {c.plan.label()}: {'; '.join(c.filters.failures)}")
        if user.current_policy:
            switching_report(fit, user, plans or [c.plan for c in rejected], top)
        return

    print(f"\n=== Your result ({user.city}, sum insured {inr(user.sum_insured)}, "
          f"{len(fit)} of {len(fit) + len(rejected)} plans fit your filters; "
          f"showing {len(cards)}) ===")
    print(headline(cards))
    marks = {"filter": "Meets your filter", "unconfirmed": "Can't confirm yet", "strength": "Strength", "tradeoff": "Trade-off"}
    for i, c in enumerate(cards):
        print(f"\n{'Best suited' if i == 0 else 'Also suited'}: {c.plan.label()}  "
              f"(fit {c.total:g}/100, {c.coverage:.0%} of the fine print known; approx. premium {premium_cell(c)})")
        for r in explain(c, [o for o in fit if o is not c], user, n=3 if i == 0 else 2):
            src = f"  [{r.source}]" if r.source else ""
            print(f"  - {marks[r.kind]}: {r.text}{src}")
    if rejected:
        print("\nRuled out by your filters:")
        for c in rejected:
            print(f"  x {c.plan.label()}: {'; '.join(c.filters.failures)}")
    if user.current_policy:
        switching_report(fit, user, plans or [c.plan for c in fit + rejected], top)

    print("\n=== Side-by-side ===")
    header = ["", *[c.plan.label() for c in cards]]
    rows = [header,
            ["Fit score /100", *[f"{c.total}" for c in cards]],
            ["Possible range (unknowns)", *[f"{c.score_range[0]:g}-{c.score_range[1]:g}" for c in cards]],
            ["Data coverage", *[f"{c.coverage:.0%}" for c in cards]],
            ["Approx. premium, nearest profile", *[premium_cell(c) for c in cards]]]
    ref = common_reference([c.plan for c in cards], user)
    if ref and len(ref[1]) > 1:
        label, ests = ref
        rows.append([f"Same-profile ref. ({label})", *[f"~{inr(ests[c.plan.id].best)}" if c.plan.id in ests else "-" for c in cards]])
    for cat in Category:
        rows.append([f"  {cat.value}", *[str(c.by_category.get(cat, "-")) for c in cards]])
    for cid in KEY_ROWS:
        crit = BY_ID[cid]
        cells = []
        for c in cards:
            cv = c.plan.values.get(cid)
            cells.append(fmt(cid, cv.value, cv.confidence) if cv else fmt(cid, None))
        rows.append([("! " if crit.rejection_risk else "  ") + crit.label, *cells])
    print(table(rows))
    print("(! = clause that commonly causes rejections or deductions; ~ = low-confidence value; "
          "? = not yet extracted, ask the insurer)\n"
          "(Premiums marked 'insurer table' come from the insurer's filed premium table: base plan, excl. GST, before "
          "discounts/loadings. Others marked ~ are indicative public figures for a reference profile. Not quotes.)")

    scenario = ClaimScenario(bill=5_00_000, room_rent_per_day=8_000, days=5, patient_age=user.oldest)
    print(f"\n=== Claim simulator: {inr(scenario.bill)} bill, {scenario.days} days in a "
          f"{inr(scenario.room_rent_per_day)}/day room ===")
    for c in cards:
        paid, steps = simulate_claim(c.plan, scenario, user)
        detail = "; ".join(f"{name} -{inr(amt)}" for name, amt in steps) or "no deductions"
        print(f"  {c.plan.label()}: pays {inr(paid)} ({detail})")
    print("  (Unknown terms are treated as not applying, so read this as a best case.)")

    for c in cards:
        verified = sum(1 for cv in c.plan.values.values() if cv.verified)
        print(f"\n--- {c.plan.label()}{f' (UIN {c.plan.uin})' if c.plan.uin else ''}: "
              f"{len(c.plan.values)} data points, {verified} verified against policy wording ---")
        for h in c.plan.highlights:
            print(f"  [+     ] {h}")
        if c.priced:
            print(f"  [PRICE ] {c.priced.describe()}")
            for cav in c.priced.caveats:
                print(f"           {cav}")
            print(f"           Source: {c.priced.source}{f' (page {c.priced.page})' if c.priced.page else ''}")
        elif c.premium is None and c.approx:
            print(f"  [PRICE ] {c.approx.describe()}")
            if not c.approx.close:
                print("           That reference profile differs from your family; get a real quote.")
            if c.approx.estimate.caveat:
                print(f"           {c.approx.estimate.caveat}")
        for g in sorted(c.gotchas, key=lambda g: ("high", "medium", "info").index(g.severity)):
            print(f"  [{g.severity.upper():6}] {g.text}")
        for flag in c.irdai_flags:
            print(f"  [CHECK ] Data looks inconsistent with current IRDAI rules (likely an extraction error or an "
                  f"older wording, under review): {flag}")
        for u in c.filters.unverified + c.to_verify:
            print(f"  [VERIFY] {u}")
        price = c.premium if c.premium is not None else (c.approx.estimate.best if c.approx and c.approx.close else None)
        if user.old_tax_regime and price is not None:
            ded = india.section_80d_deduction(price, self_or_spouse_senior=user.oldest >= india.SENIOR_AGE)
            print(f"  [80D   ] Deduction {inr(ded)} saves about {inr(india.tax_saved(ded, user.tax_slab_pct))} in tax "
                  f"at {user.tax_slab_pct:g}% slab")
        if (doc := c.plan.documents.get("policy_wording") or next(iter(c.plan.documents.values()), "")):
            print(f"  [SOURCE] {doc}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Compare Indian health insurance plans against your criteria.")
    ap.add_argument("--demo", action="store_true", help="use a canned profile instead of asking")
    ap.add_argument("--demo-switch", action="store_true", help="canned profile of someone with an existing policy")
    ap.add_argument("--data", default=str(DATA_DIR), help="directory with plans.json and insurers.json")
    ap.add_argument("--top", type=int, default=3)
    args = ap.parse_args(argv)

    data = Path(args.data)
    plans = load_plans(data / "plans.json", load_insurers(data / "insurers.json"))
    insurers = load_insurers(data / "insurers.json")
    user = demo_switch_profile() if args.demo_switch else demo_profile() if args.demo else questionnaire(plans, insurers)
    fit, rejected = rank(plans, user, top=None)
    report(fit, rejected, user, top=args.top, plans=plans)


if __name__ == "__main__":
    main()

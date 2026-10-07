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
from .models import DealBreakers, Member, UserProfile, load_insurers, load_plans

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


def questionnaire() -> UserProfile:
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
                       deal_breakers=db, employer_cover=employer, old_tax_regime=old_regime)


def demo_profile() -> UserProfile:
    return UserProfile(
        members=[Member("You", 34, conditions=["hypertension"]), Member("Spouse", 32)],
        city="Mumbai",
        sum_insured=10_00_000,
        deal_breakers=DealBreakers(no_room_rent_cap=True, max_ped_wait_months=36),
        employer_cover=5_00_000,
        old_tax_regime=True,
    )


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


def report(fit: list[ScoreCard], rejected: list[ScoreCard], user: UserProfile, top: int = 3) -> None:
    """`fit`: every plan that passed the filters, best first; the first `top` are explained."""
    cards = fit[:top]
    if not cards:
        print("\nNo plan passes all your filters. Relax one and retry:")
        for c in rejected:
            print(f"  x {c.plan.label()}: {'; '.join(c.filters.failures)}")
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
    ap.add_argument("--data", default=str(DATA_DIR), help="directory with plans.json and insurers.json")
    ap.add_argument("--top", type=int, default=3)
    args = ap.parse_args(argv)

    data = Path(args.data)
    plans = load_plans(data / "plans.json", load_insurers(data / "insurers.json"))
    user = demo_profile() if args.demo else questionnaire()
    fit, rejected = rank(plans, user, top=None)
    report(fit, rejected, user, top=args.top)


if __name__ == "__main__":
    main()

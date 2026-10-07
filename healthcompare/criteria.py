"""The criteria catalog: every data point we collect for an Indian retail health
insurance plan (IRDAI-regulated).

Each criterion says *how* to score it (numeric bounds, good boolean value, or
ordered enum options), *why* it matters, and whether it is a rejection /
deduction risk -- the fine print that turns a claim into a partial payout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Kind(str, Enum):
    NUMBER = "number"  # scored between `worst` and `best`
    BOOL = "bool"  # scored 1 if value == `good` else 0
    ENUM = "enum"  # `options` ordered best -> worst
    TEXT = "text"  # informational, not scored


class Source(str, Enum):
    POLICY_WORDING = "policy_wording"
    CIS = "customer_information_sheet"
    PROSPECTUS = "prospectus"
    BROCHURE = "brochure"
    PREMIUM_CHART = "premium_chart"
    IRDAI_ANNUAL_REPORT = "irdai_annual_report"
    PUBLIC_DISCLOSURE = "insurer_public_disclosure"
    OMBUDSMAN = "ombudsman_report"
    NETWORK_LIST = "network_hospital_list"
    WEBSITE = "website"


class Category(str, Enum):
    INSURER = "Insurer track record"
    CLAIMS = "Claim process & service"
    ROOM_LIMITS = "Room, ICU & proportionate deduction"
    COST_SHARING = "Co-pay, deductibles & sub-limits"
    WAITING = "Waiting periods"
    COVERAGE = "Hospitalisation coverage"
    EXTRAS = "Extended benefits"
    SUM_INSURED = "Sum insured mechanics"
    UNDERWRITING = "Underwriting & exclusions"
    PRICING = "Premium & renewal"


@dataclass(frozen=True)
class Criterion:
    id: str
    category: Category
    label: str
    kind: Kind
    why: str
    unit: str = ""
    best: float | None = None
    worst: float | None = None
    good: bool | None = None
    options: tuple[str, ...] = ()
    band: tuple[float, float] | None = None  # NUMBER: ideal range; scores fall off on both sides
    over: float | None = None  # with band: value above the band that scores 0
    rejection_risk: bool = False
    weight: int = 2  # 1 (nice to know) .. 5 (critical)
    sources: tuple[Source, ...] = (Source.POLICY_WORDING,)
    tags: frozenset[str] = field(default_factory=frozenset)

    def score(self, value: object) -> float | None:
        """Normalise a value to 0..1 (1 = best). None if unscorable."""
        if value is None:
            return None
        if self.kind is Kind.NUMBER and self.band:
            lo, hi = self.band
            v = float(value)
            if v < lo:
                return max(0.0, (v - self.worst) / (lo - self.worst))
            if v > hi:
                return max(0.0, (self.over - v) / (self.over - hi))
            return 1.0
        if self.kind is Kind.NUMBER:
            assert self.best is not None and self.worst is not None
            span = self.best - self.worst
            return max(0.0, min(1.0, (float(value) - self.worst) / span))
        if self.kind is Kind.BOOL:
            return 1.0 if bool(value) == self.good else 0.0
        if self.kind is Kind.ENUM:
            if value not in self.options:
                return None
            if len(self.options) == 1:
                return 1.0
            return 1.0 - self.options.index(value) / (len(self.options) - 1)
        return None


def _c(*args, tags: str = "", **kwargs) -> Criterion:
    return Criterion(*args, tags=frozenset(tags.split()), **kwargs)


C, K, S = Category, Kind, Source
_IRDAI = (S.IRDAI_ANNUAL_REPORT, S.PUBLIC_DISCLOSURE)

CRITERIA: tuple[Criterion, ...] = (
    # ------------------------------------------------------------------ insurer
    _c("csr_count", C.INSURER, "Claim settlement ratio (by number)", K.NUMBER, unit="%", best=99, worst=85, weight=4, sources=_IRDAI,
       why="Share of claims paid. Headline number, but easy to inflate with many small claims."),
    _c("csr_amount", C.INSURER, "Claim settlement ratio (by amount)", K.NUMBER, unit="%", best=95, worst=70, weight=5, sources=_IRDAI,
       why="Share of claimed rupees actually paid. A big gap vs count-CSR means large claims get cut or rejected."),
    _c("repudiation_pct", C.INSURER, "Claims repudiated", K.NUMBER, unit="%", best=1, worst=12, weight=4, sources=_IRDAI, rejection_risk=True,
       why="Outright rejections. The number to watch if you fear a denied claim."),
    _c("claims_pending_pct", C.INSURER, "Claims pending at year end", K.NUMBER, unit="%", best=0.5, worst=8, weight=2, sources=_IRDAI,
       why="High pendency means slow or stuck reimbursements."),
    _c("claims_paid_30d_pct", C.INSURER, "Claims settled within 30 days", K.NUMBER, unit="%", best=98, worst=75, weight=3, sources=(S.PUBLIC_DISCLOSURE,),
       why="Claim ageing from NL disclosures; how long reimbursement money takes."),
    _c("icr", C.INSURER, "Incurred claim ratio", K.NUMBER, unit="%", best=75, worst=40, band=(65, 90), over=115, weight=2, sources=_IRDAI,
       why="Claims paid / premium earned. Very low = stingy payer; very high (>100) = premium hikes likely. ~60-85 is healthy."),
    _c("complaints_per_10k", C.INSURER, "Grievances per 10,000 claims", K.NUMBER, best=5, worst=80, weight=4, sources=(S.PUBLIC_DISCLOSURE,),
       why="Normalised complaint volume; strongest proxy for real-world claim friction."),
    _c("ombudsman_complaints_per_lakh", C.INSURER, "Ombudsman complaints per lakh policies", K.NUMBER, best=2, worst=40, weight=3, sources=(S.OMBUDSMAN,),
       why="Escalated disputes customers felt strongly enough to take outside the insurer."),
    _c("solvency_ratio", C.INSURER, "Solvency ratio", K.NUMBER, best=2.5, worst=1.5, weight=1, sources=(S.PUBLIC_DISCLOSURE,),
       why="IRDAI minimum is 1.5. Near the floor means financial stress."),
    _c("in_house_claims", C.INSURER, "Claims handled in-house (no TPA)", K.BOOL, good=True, weight=2, sources=(S.WEBSITE, S.POLICY_WORDING),
       why="TPAs add a middle layer; in-house teams usually decide faster."),
    _c("insurer_type", C.INSURER, "Insurer type", K.ENUM, options=("standalone_health", "private_general", "psu_general"), weight=1, sources=(S.WEBSITE,),
       why="Standalone health insurers focus only on health; PSUs are cheaper but often slower on service."),
    _c("years_in_health", C.INSURER, "Years writing health insurance", K.NUMBER, best=15, worst=2, weight=1, sources=(S.WEBSITE,),
       why="Short history = little renewal/pricing track record to judge."),

    # ------------------------------------------------------------------ claims & service
    _c("network_hospitals", C.CLAIMS, "Network hospitals (national)", K.NUMBER, best=14000, worst=4000, weight=2, sources=(S.NETWORK_LIST,),
       why="Headline count matters less than whether *your* hospitals are in it (checked separately)."),
    _c("cashless_everywhere", C.CLAIMS, "Cashless at non-network hospitals", K.BOOL, good=True, weight=2, sources=(S.WEBSITE,),
       why="'Cashless everywhere' lets you get cashless with advance notice even outside the network."),
    _c("excluded_hospitals_list", C.CLAIMS, "Has de-listed / excluded hospitals list", K.BOOL, good=False, weight=3, rejection_risk=True, sources=(S.WEBSITE, S.POLICY_WORDING),
       why="Treatment at an excluded hospital is NOT paid (except life-threatening emergencies). Check before admission."),
    _c("cashless_intimation_planned_hrs", C.CLAIMS, "Intimation needed before planned admission", K.NUMBER, unit="hours", best=24, worst=96, weight=2, rejection_risk=True,
       why="Missing the pre-intimation window can lose cashless or trigger a dispute."),
    _c("emergency_intimation_hrs", C.CLAIMS, "Intimation window after emergency admission", K.NUMBER, unit="hours", best=48, worst=24, weight=2, rejection_risk=True,
       why="Late intimation is a classic technical ground for denial."),
    _c("reimbursement_doc_days", C.CLAIMS, "Days to submit reimbursement documents", K.NUMBER, unit="days", best=30, worst=7, weight=2, rejection_risk=True,
       why="Short windows after discharge catch people out; delayed submissions get rejected."),
    _c("non_network_copay_pct", C.CLAIMS, "Co-pay for treatment at non-network hospital", K.NUMBER, unit="%", best=0, worst=30, weight=3, rejection_risk=True,
       why="Some plans make you pay a share if you go outside the network -- a hidden co-pay."),
    _c("hospital_min_beds", C.CLAIMS, "Minimum beds in 'hospital' definition", K.NUMBER, best=10, worst=15, weight=2, rejection_risk=True,
       why="Small-town nursing homes with fewer beds than the definition (10 in towns under 10 lakh, else 15) are not 'hospitals': claim rejected."),
    _c("tpa_name", C.CLAIMS, "TPA handling claims", K.TEXT, weight=1, sources=(S.POLICY_WORDING, S.WEBSITE),
       why="Check the TPA's own complaint record; it is the TPA that will process your claim."),
    _c("digital_claims", C.CLAIMS, "Fully digital claim filing", K.BOOL, good=True, weight=1, sources=(S.WEBSITE,),
       why="Upload-and-track removes courier delays and 'document not received' disputes."),

    # ------------------------------------------------------------------ room & proportionate deduction
    _c("room_rent_limit", C.ROOM_LIMITS, "Room rent limit", K.ENUM, weight=5, rejection_risk=True, sources=(S.POLICY_WORDING, S.CIS),
       options=("no_limit", "any_room_except_suite", "single_private_room", "shared_room", "2pct_si_per_day", "1pct_si_per_day"),
       why="The #1 hidden deduction. Exceed the cap and proportionate deduction cuts the ENTIRE bill, not just the room."),
    _c("icu_limit", C.ROOM_LIMITS, "ICU charge limit", K.ENUM, weight=3, rejection_risk=True,
       options=("no_limit", "4pct_si_per_day", "2pct_si_per_day"),
       why="ICU days are the most expensive; a cap here bites hard on serious illness."),
    _c("proportionate_deduction", C.ROOM_LIMITS, "Proportionate deduction clause applies", K.BOOL, good=False, weight=5, rejection_risk=True,
       why="If you take a costlier room, doctor fees, OT, nursing etc. are paid in the same ratio as room rent. A Rs 5L bill can pay Rs 3L."),
    _c("room_category_upgrade_rider", C.ROOM_LIMITS, "Room-rent waiver add-on available", K.BOOL, good=True, weight=1,
       why="An add-on that removes the room cap; worth it if the base plan caps."),

    # ------------------------------------------------------------------ co-pay, deductibles, sub-limits
    _c("general_copay_pct", C.COST_SHARING, "Co-pay on every claim", K.NUMBER, unit="%", best=0, worst=30, weight=5, rejection_risk=True,
       why="You pay this share of every admissible claim, forever."),
    _c("age_copay_pct", C.COST_SHARING, "Age-based co-pay", K.NUMBER, unit="%", best=0, worst=30, weight=4, rejection_risk=True, tags="senior",
       why="Kicks in at a certain entry or attained age, often exactly when you claim most."),
    _c("age_copay_from_age", C.COST_SHARING, "Age-based co-pay applies from age", K.NUMBER, unit="years", best=80, worst=56, weight=2, tags="senior",
       why="Whether it is by *entry* age or *attained* age changes everything at renewal."),
    _c("zone_copay_pct", C.COST_SHARING, "Zone co-pay (treated in costlier city than bought)", K.NUMBER, unit="%", best=0, worst=20, weight=3, rejection_risk=True,
       why="Bought a cheaper 'Zone B/C' premium but got treated in Mumbai/Delhi? Extra co-pay applies."),
    _c("deductible_amount", C.COST_SHARING, "Mandatory deductible", K.NUMBER, unit="Rs", best=0, worst=100000, weight=4,
       why="First Rs X of each claim/year is yours. Fine for top-ups, a trap in a base plan."),
    _c("disease_sublimits", C.COST_SHARING, "Disease/procedure sub-limits", K.ENUM, weight=5, rejection_risk=True,
       options=("none", "few_minor", "cataract_only", "many_common_procedures"),
       why="Caps on cataract, knee replacement, hernia, piles etc. pay a fixed amount regardless of your SI."),
    _c("notable_sublimits", C.COST_SHARING, "Other caps found in the wording", K.TEXT, weight=1,
       why="Free-text caveats, e.g. a per-claim cap on a few robotic surgeries, that no standard field captures."),
    _c("cataract_limit", C.COST_SHARING, "Cataract limit per eye", K.NUMBER, unit="Rs", best=200000, worst=20000, weight=2, tags="senior",
       why="Most common senior surgery; caps of Rs 20-40k are common and far below private-hospital cost."),
    _c("modern_treatment_limit_pct", C.COST_SHARING, "Modern treatments covered up to (% of SI)", K.NUMBER, unit="%", best=100, worst=25, weight=3, rejection_risk=True,
       why="Robotic surgery, immunotherapy, oral chemo, stem cell, deep brain stimulation etc. are often capped at 25-50% of SI."),
    _c("consumables_covered", C.COST_SHARING, "Consumables / non-payable items covered", K.BOOL, good=True, weight=4, rejection_risk=True,
       why="Gloves, PPE, syringes, belts, etc. (IRDAI non-payables list) can be 5-15% of a bill. Often add-on only."),
    _c("reasonable_customary_clause", C.COST_SHARING, "'Reasonable & customary charges' clause", K.BOOL, good=False, weight=2, rejection_risk=True,
       why="Lets the insurer pay less than billed if it thinks the hospital overcharged."),

    # ------------------------------------------------------------------ waiting periods
    _c("initial_waiting_days", C.WAITING, "Initial waiting period", K.NUMBER, unit="days", best=0, worst=30, weight=2,
       why="No claims (except accidents) for this many days after first purchase."),
    _c("ped_waiting_months", C.WAITING, "Pre-existing disease waiting", K.NUMBER, unit="months", best=0, worst=36, weight=5, rejection_risk=True, tags="ped",
       why="Diabetes, BP, thyroid etc. not covered until this ends. IRDAI cap is 36 months."),
    _c("ped_waiting_reducible", C.WAITING, "PED waiting reducible via add-on", K.BOOL, good=True, weight=2, tags="ped",
       why="Some plans let you buy down PED waiting to 1 year or even 30 days."),
    _c("ped_lookback_months", C.WAITING, "PED look-back period (definition)", K.NUMBER, unit="months", best=0, worst=48, weight=2, rejection_risk=True, tags="ped",
       why="Anything diagnosed/treated in this window before purchase counts as pre-existing."),
    _c("specific_disease_waiting_months", C.WAITING, "Specific illness waiting", K.NUMBER, unit="months", best=0, worst=36, weight=4, rejection_risk=True,
       why="Hernia, cataract, joint replacement, stones, ENT etc. excluded for this long even if you never had them."),
    _c("specific_disease_list_size", C.WAITING, "Number of listed specific illnesses", K.NUMBER, best=5, worst=40, weight=2,
       why="A longer list means more everyday surgeries blocked in early years."),
    _c("personal_waiting_months", C.WAITING, "Person-specific waiting the insurer may impose", K.NUMBER, unit="months", best=0, worst=48, weight=3, rejection_risk=True, tags="ped",
       why="Some wordings let underwriters add a personal waiting period (up to 48 months) for a declared condition on top of the PED wait. Check the schedule."),
    _c("maternity_waiting_months", C.WAITING, "Maternity waiting", K.NUMBER, unit="months", best=9, worst=48, weight=3, tags="maternity",
       why="Plan pregnancy timelines around this; usually 2-4 years."),
    _c("bariatric_waiting_months", C.WAITING, "Bariatric surgery waiting", K.NUMBER, unit="months", best=0, worst=48, weight=1,
       why="Often 3+ years, with BMI conditions attached."),
    _c("moratorium_months", C.WAITING, "Moratorium period", K.NUMBER, unit="months", best=60, worst=96, weight=3, rejection_risk=True,
       why="After this many continuous months, the insurer cannot reject for non-disclosure (except proven fraud). IRDAI cut it from 96 to 60 months in 2024; anything longer is an old wording."),
    _c("waiting_credit_on_port", C.WAITING, "Waiting periods credited on portability", K.BOOL, good=True, weight=2,
       why="Switching insurers should carry over waiting periods already served."),

    # ------------------------------------------------------------------ hospitalisation coverage
    _c("pre_hosp_days", C.COVERAGE, "Pre-hospitalisation cover", K.NUMBER, unit="days", best=90, worst=30, weight=3,
       why="Tests and consults before admission."),
    _c("post_hosp_days", C.COVERAGE, "Post-hospitalisation cover", K.NUMBER, unit="days", best=180, worst=60, weight=3,
       why="Follow-ups, medicines, physio after discharge."),
    _c("day_care_all", C.COVERAGE, "All day-care procedures covered", K.BOOL, good=True, weight=3,
       why="Chemo, dialysis, cataract etc. under 24h. A fixed list can leave newer procedures out."),
    _c("min_hospitalisation_hrs", C.COVERAGE, "Minimum hospitalisation for a claim", K.NUMBER, unit="hours", best=2, worst=24, weight=2, rejection_risk=True,
       why="Claims for short stays not on the day-care list are rejected as 'not hospitalisation'."),
    _c("domiciliary", C.COVERAGE, "Domiciliary (home) hospitalisation", K.BOOL, good=True, weight=2,
       why="Treatment at home when a hospital bed isn't available or the patient can't be moved."),
    _c("home_care_treatment", C.COVERAGE, "Hospital-at-home / home care", K.BOOL, good=True, weight=1,
       why="Newer cover for treating conditions like dengue/COVID at home with a care provider."),
    _c("ayush_covered", C.COVERAGE, "AYUSH up to SI", K.BOOL, good=True, weight=1,
       why="Ayurveda/homeopathy inpatient care; some plans cap it heavily."),
    _c("road_ambulance_limit", C.COVERAGE, "Road ambulance limit per hospitalisation", K.NUMBER, unit="Rs", best=10000, worst=1500, weight=1,
       why="Small but frequently claimed."),
    _c("air_ambulance", C.COVERAGE, "Air ambulance", K.BOOL, good=True, weight=1,
       why="Rare but catastrophic cost when needed."),
    _c("organ_donor", C.COVERAGE, "Organ donor expenses", K.BOOL, good=True, weight=2,
       why="Harvesting costs for the donor in a transplant."),
    _c("mental_health_parity", C.COVERAGE, "Mental illness covered like physical", K.BOOL, good=True, weight=2,
       why="Required by law, but check for sub-limits or listed-hospital-only rules."),
    _c("hiv_std_covered", C.COVERAGE, "HIV/AIDS & STD treatment", K.BOOL, good=True, weight=1,
       why="Mandated by HIV Act 2017 but still excluded in some older wordings."),

    # ------------------------------------------------------------------ extended benefits
    _c("maternity_covered", C.EXTRAS, "Maternity covered", K.BOOL, good=True, weight=2, tags="maternity",
       why="Few retail base plans include it; usually an add-on with long waiting."),
    _c("maternity_limit", C.EXTRAS, "Maternity limit (normal/C-section)", K.NUMBER, unit="Rs", best=100000, worst=15000, weight=2, tags="maternity",
       why="Typically a fixed sub-limit well below actual cost."),
    _c("newborn_day1", C.EXTRAS, "Newborn covered from day 1", K.BOOL, good=True, weight=2, tags="maternity",
       why="NICU bills can exceed delivery costs."),
    _c("opd_cover", C.EXTRAS, "OPD consultation/pharmacy cover", K.BOOL, good=True, weight=1,
       why="Usually priced in; check if it's worth the extra premium."),
    _c("annual_health_checkup", C.EXTRAS, "Annual health check-up", K.BOOL, good=True, weight=1,
       why="Some only after a claim-free year."),
    _c("second_opinion", C.EXTRAS, "E-second opinion for major illness", K.BOOL, good=True, weight=1,
       why="Useful before major surgery."),
    _c("global_cover", C.EXTRAS, "Treatment abroad", K.BOOL, good=True, weight=1,
       why="Usually planned treatment for listed illnesses with a deductible."),
    _c("daily_hospital_cash", C.EXTRAS, "Daily hospital cash", K.BOOL, good=True, weight=1,
       why="Covers incidentals; not a reason to choose a plan."),

    # ------------------------------------------------------------------ sum insured mechanics
    _c("restoration_type", C.SUM_INSURED, "Restoration of sum insured", K.ENUM, weight=3,
       options=("unlimited_any_illness", "once_any_illness", "once_unrelated_only", "none"),
       why="'Unrelated illness only' doesn't help a relapse of the same cancer in the same year."),
    _c("restoration_trigger", C.SUM_INSURED, "Restoration triggers on", K.ENUM, weight=2,
       options=("partial_use", "complete_exhaustion", "not_applicable"),
       why="If it only refills after SI is fully used, a big first claim that just exceeds SI is not helped."),
    _c("restoration_same_member", C.SUM_INSURED, "Restored SI usable by same member", K.BOOL, good=True, weight=2,
       why="In floaters, some plans bar the person who used up the SI."),
    _c("ncb_pct_per_year", C.SUM_INSURED, "No-claim bonus per claim-free year", K.NUMBER, unit="% of SI", best=100, worst=10, weight=3,
       why="Grows cover without extra premium."),
    _c("ncb_max_pct", C.SUM_INSURED, "No-claim bonus maximum", K.NUMBER, unit="% of SI", best=500, worst=50, weight=2,
       why="Cap on cumulative bonus."),
    _c("ncb_reduces_on_claim", C.SUM_INSURED, "Bonus reduces after a claim", K.BOOL, good=False, weight=2,
       why="Some plans remove the bonus when you claim, so the SI you planned around shrinks."),
    _c("inflation_protector", C.SUM_INSURED, "Inflation-linked SI increase", K.BOOL, good=True, weight=1,
       why="Keeps cover in line with medical inflation (~12-14%/yr in India)."),
    _c("super_topup_same_insurer", C.SUM_INSURED, "Super top-up available from same insurer", K.BOOL, good=True, weight=1,
       why="Base Rs 5-10L + super top-up Rs 50L-1Cr is the cheapest way to big cover in India; same insurer avoids two claim processes."),
    _c("floater_per_member_cap", C.SUM_INSURED, "Per-member cap within floater", K.BOOL, good=False, weight=2,
       why="A 'family floater' that caps each member is closer to small individual covers."),

    # ------------------------------------------------------------------ underwriting & exclusions
    _c("pre_policy_medicals_age", C.UNDERWRITING, "Pre-policy medical tests from age", K.NUMBER, unit="years", best=45, worst=70, weight=2, rejection_risk=True,
       why="Counterintuitive: tests at purchase protect you. No tests means non-disclosure disputes surface at claim time."),
    _c("ped_permanent_exclusion_option", C.UNDERWRITING, "Insurer may permanently exclude a disclosed condition", K.BOOL, good=False, weight=3, rejection_risk=True, tags="ped",
       why="IRDAI allows named permanent exclusions for some conditions. Read your acceptance letter."),
    _c("premium_loading_for_ped", C.UNDERWRITING, "Premium loading for declared conditions", K.BOOL, good=False, weight=2, tags="ped",
       why="Declared diabetes/BP can add 10-100% loading instead of a waiting period."),
    _c("adventure_sports_excluded", C.UNDERWRITING, "Adventure sports injuries excluded", K.BOOL, good=False, weight=1, rejection_risk=True,
       why="Trekking, scuba, biking events: a common surprise rejection."),
    _c("substance_related_excluded", C.UNDERWRITING, "Alcohol/substance-related illness excluded", K.BOOL, good=False, weight=2, rejection_risk=True,
       why="Liver/pancreas claims are often rejected citing alcohol history recorded in hospital notes."),
    _c("obesity_treatment_conditions", C.UNDERWRITING, "Obesity treatment restricted (BMI/comorbidity rules)", K.BOOL, good=False, weight=1, rejection_risk=True,
       why="Bariatric claims are rejected if BMI/comorbidity thresholds aren't documented."),
    _c("investigation_only_excluded", C.UNDERWRITING, "Admission 'for investigation only' excluded", K.BOOL, good=False, weight=2, rejection_risk=True,
       why="Admitted for tests with no active treatment? Rejected. Ensure the discharge summary shows treatment."),
    _c("infertility_covered", C.UNDERWRITING, "Infertility/IVF covered", K.BOOL, good=True, weight=1, tags="maternity",
       why="Almost always excluded; rare plans offer limited cover."),

    # ------------------------------------------------------------------ premium & renewal
    _c("max_entry_age", C.PRICING, "Maximum entry age", K.NUMBER, unit="years", best=99, worst=55, weight=2, tags="senior",
       why="IRDAI removed the entry age cap in 2024; older plans may still have one."),
    _c("senior_hike_last_pct", C.PRICING, "Last renewal hike for 60+ policyholders", K.NUMBER, unit="%", best=0, worst=25, weight=2, tags="senior", sources=(S.WEBSITE,),
       why="IRDAI (Jan 2025) requires prior consultation for hikes above 10%/yr for senior citizens."),
    _c("premium_hike_history_pct", C.PRICING, "Avg. portfolio premium hike (last 3 yrs)", K.NUMBER, unit="%/yr", best=3, worst=25, weight=3, sources=(S.WEBSITE, S.PREMIUM_CHART),
       why="Today's cheap plan can get expensive fast; insurers re-price whole products."),
    _c("age_band_width_years", C.PRICING, "Age band width after 45", K.NUMBER, unit="years", best=1, worst=10, weight=1, sources=(S.PREMIUM_CHART,),
       why="Wide bands mean sudden big jumps at 46/51/56/61 rather than gradual increases."),
    _c("multi_year_discount_pct", C.PRICING, "Multi-year tenure discount", K.NUMBER, unit="%", best=15, worst=0, weight=1, sources=(S.PREMIUM_CHART,),
       why="Locks today's rate for 2-3 years."),
    _c("premium_age_lock", C.PRICING, "Premium frozen at entry age until first claim", K.BOOL, good=True, weight=2,
       why="'Lock the clock' / 'age freeze' style features keep you on the entry-age premium band until you claim."),
    _c("emi_available", C.PRICING, "Monthly/quarterly payment", K.BOOL, good=True, weight=1, sources=(S.WEBSITE,),
       why="Helps affordability for higher SIs."),
    _c("portability_in", C.PRICING, "Accepts portability from other insurers", K.BOOL, good=True, weight=1,
       why="Lets you move in later without restarting waiting periods (apply 15-60 days before renewal)."),
    _c("lifelong_renewal", C.PRICING, "Lifelong renewability", K.BOOL, good=True, weight=4,
       why="Mandatory now, but verify for older or group-converted plans."),
    _c("product_withdrawal_risk", C.PRICING, "Product is old/being withdrawn", K.BOOL, good=False, weight=2, sources=(S.WEBSITE,),
       why="Closed products shrink into a sicker, older pool, and that drives premium hikes."),
)

BY_ID: dict[str, Criterion] = {c.id: c for c in CRITERIA}
assert len(BY_ID) == len(CRITERIA), "duplicate criterion id"


def by_category() -> dict[Category, list[Criterion]]:
    out: dict[Category, list[Criterion]] = {cat: [] for cat in Category}
    for c in CRITERIA:
        out[c.category].append(c)
    return out

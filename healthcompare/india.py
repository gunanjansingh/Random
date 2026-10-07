"""India-specific rules and reference data: IRDAI limits, zones, Section 80D, insurers.

Regulatory figures reflect the IRDAI Master Circular on Health Insurance
(May 2024) and later circulars. Re-verify against irdai.gov.in before
relying on them; they change.
"""

from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------- IRDAI rules

IRDAI_MAX_PED_WAITING_MONTHS = 36
IRDAI_MAX_SPECIFIC_DISEASE_WAITING_MONTHS = 36
IRDAI_MORATORIUM_MONTHS = 60
IRDAI_CASHLESS_AUTH_MINUTES = 60  # decide cashless pre-auth within 1 hour
IRDAI_DISCHARGE_AUTH_MINUTES = 180  # final discharge authorisation within 3 hours
IRDAI_SENIOR_PREMIUM_HIKE_CAP_PCT = 10  # yearly hike for 60+ needs IRDAI consultation beyond this
SENIOR_AGE = 60

# Hospital definition: minimum inpatient beds for a claim to be admissible.
HOSPITAL_MIN_BEDS_SMALL_TOWN = 10  # towns with population < 10 lakh
HOSPITAL_MIN_BEDS_OTHER = 15


@dataclass(frozen=True)
class RuleViolation:
    criterion: str
    message: str


def irdai_violations(values: dict[str, object]) -> list[RuleViolation]:
    """Values that break current IRDAI limits. These are either extraction errors
    or an old product still being sold on a pre-2024 wording; either way they
    need a human to look at them."""
    out: list[RuleViolation] = []

    def over(cid: str, cap: float, what: str) -> None:
        v = values.get(cid)
        if isinstance(v, (int, float)) and v > cap:
            out.append(RuleViolation(cid, f"{what} is {v} months; IRDAI cap is {cap}"))

    over("ped_waiting_months", IRDAI_MAX_PED_WAITING_MONTHS, "PED waiting")
    over("specific_disease_waiting_months", IRDAI_MAX_SPECIFIC_DISEASE_WAITING_MONTHS, "Specific illness waiting")
    over("moratorium_months", IRDAI_MORATORIUM_MONTHS, "Moratorium")
    if values.get("lifelong_renewal") is False:
        out.append(RuleViolation("lifelong_renewal", "Renewal is not lifelong; IRDAI requires lifelong renewability"))
    if values.get("hiv_std_covered") is False:
        out.append(RuleViolation("hiv_std_covered", "HIV/AIDS excluded, which conflicts with the HIV & AIDS Act 2017"))
    if values.get("mental_health_parity") is False:
        out.append(RuleViolation("mental_health_parity", "Mental illness excluded, which conflicts with the Mental Healthcare Act 2017"))
    return out


# --------------------------------------------------------------------------- zones

# Insurers that price by zone each publish their own city list, and those lists
# differ. This is an indicative default used only when a plan has no list of its
# own. Plans should carry `zone_cities` taken from their policy wording.
DEFAULT_ZONE_CITIES: dict[str, str] = {
    **dict.fromkeys(
        ["delhi", "new delhi", "gurugram", "gurgaon", "noida", "greater noida", "ghaziabad", "faridabad",
         "mumbai", "thane", "navi mumbai", "ahmedabad", "surat", "vadodara"], "A"),
    **dict.fromkeys(
        ["bengaluru", "bangalore", "chennai", "hyderabad", "secunderabad", "kolkata", "pune",
         "chandigarh", "jaipur", "lucknow", "indore", "kochi", "coimbatore", "nagpur"], "B"),
}


def zone_for_city(city: str, zone_cities: dict[str, str] | None = None) -> str:
    """Zone A = costliest metros, C = rest of India."""
    key = city.strip().lower()
    return (zone_cities or DEFAULT_ZONE_CITIES).get(key, DEFAULT_ZONE_CITIES.get(key, "C"))


# --------------------------------------------------------------------------- Section 80D

def section_80d_deduction(
    self_family_premium: int,
    parents_premium: int = 0,
    self_or_spouse_senior: bool = False,
    parents_senior: bool = False,
    preventive_checkup: int = 0,
) -> int:
    """Deduction under Section 80D (old tax regime only; the new regime allows none).

    Limits: Rs 25,000 for self/spouse/children (Rs 50,000 if either is 60+), plus
    Rs 25,000 for parents (Rs 50,000 if senior). Preventive check-ups of up to
    Rs 5,000 fall within these limits.
    """
    own_cap = 50_000 if self_or_spouse_senior else 25_000
    parents_cap = 50_000 if parents_senior else 25_000
    checkup = min(preventive_checkup, 5_000)
    own = min(self_family_premium + checkup, own_cap)
    checkup_left = max(0, checkup - max(0, own_cap - self_family_premium))
    parents = min(parents_premium + checkup_left, parents_cap) if parents_premium else 0
    return own + parents


def tax_saved(deduction: int, slab_rate_pct: float) -> int:
    """Tax saved at the user's marginal slab, including 4% health & education cess."""
    return round(deduction * slab_rate_pct / 100 * 1.04)


# --------------------------------------------------------------------------- formatting

def inr(amount: float) -> str:
    """Format rupees the Indian way: Rs 12,34,567 / Rs 5L / Rs 1.2Cr."""
    amount = round(amount)
    if amount >= 1_00_00_000:
        return f"Rs {amount / 1_00_00_000:g}Cr"
    if amount >= 1_00_000 and amount % 10_000 == 0:
        return f"Rs {amount / 1_00_000:g}L"
    s = str(abs(amount))
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    body = ",".join(groups + [tail]) if groups else tail
    return f"{'-' if amount < 0 else ''}Rs {body}"


# --------------------------------------------------------------------------- insurers to ingest

@dataclass(frozen=True)
class InsurerTarget:
    name: str
    kind: str  # standalone_health | private_general | psu_general


# Retail health insurers to cover first. Plan lists, documents and URLs are
# discovered by the ingestion pipeline. Nothing about their products is
# hard-coded here.
INSURERS: tuple[InsurerTarget, ...] = (
    InsurerTarget("Star Health and Allied Insurance", "standalone_health"),
    InsurerTarget("Care Health Insurance", "standalone_health"),
    InsurerTarget("Niva Bupa Health Insurance", "standalone_health"),
    InsurerTarget("Aditya Birla Health Insurance", "standalone_health"),
    InsurerTarget("ManipalCigna Health Insurance", "standalone_health"),
    InsurerTarget("Galaxy Health Insurance", "standalone_health"),
    InsurerTarget("Narayana Health Insurance", "standalone_health"),
    InsurerTarget("HDFC ERGO General Insurance", "private_general"),
    InsurerTarget("ICICI Lombard General Insurance", "private_general"),
    InsurerTarget("Bajaj General Insurance (formerly Bajaj Allianz)", "private_general"),
    InsurerTarget("Tata AIG General Insurance", "private_general"),
    InsurerTarget("SBI General Insurance", "private_general"),
    InsurerTarget("Digit General Insurance", "private_general"),
    InsurerTarget("Reliance General Insurance", "private_general"),
    InsurerTarget("New India Assurance", "psu_general"),
    InsurerTarget("United India Insurance", "psu_general"),
    InsurerTarget("National Insurance", "psu_general"),
    InsurerTarget("The Oriental Insurance", "psu_general"),
)

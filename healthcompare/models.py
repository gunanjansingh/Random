"""Plans and insurers (every value cited), user profiles, and deal-breakers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .criteria import BY_ID, Category
from .india import zone_for_city

ZONE_COST_RANK = {"A": 3, "B": 2, "C": 1}  # A = costliest metros

# Where a value came from, most authoritative first. Used to reconcile
# disagreeing sources and to decide what still needs verification.
SOURCE_PRECEDENCE = (
    "policy_wording",
    "customer_information_sheet",
    "prospectus",
    "brochure",
    "product_page",
    "insurer_blog",
    "irdai",
    "public_disclosure",
    "secondary",  # broker / aggregator / press summarising primary data
)


@dataclass
class Citation:
    source: str  # one of SOURCE_PRECEDENCE
    url: str
    quote: str = ""  # verbatim text, or a close paraphrase when marked unverified
    page: int | None = None
    retrieved: str = ""  # ISO date


@dataclass
class CitedValue:
    value: object
    citation: Citation | None = None
    confidence: float = 1.0  # 0..1; extraction confidence, not plan quality
    verified: bool = False  # True only after a check against the primary document
    note: str = ""
    period: str = ""  # for time-bound metrics, e.g. "FY2024-25"
    alternates: list[CitedValue] = field(default_factory=list)  # other sources that disagree

    @property
    def conflicting(self) -> bool:
        return any(a.value != self.value for a in self.alternates)

    @classmethod
    def from_raw(cls, raw: object) -> CitedValue:
        if not (isinstance(raw, dict) and "value" in raw):
            return cls(value=raw)
        cit = raw.get("citation")
        return cls(
            value=raw["value"],
            citation=Citation(**cit) if cit else None,
            confidence=raw.get("confidence", 1.0),
            verified=raw.get("verified", False),
            note=raw.get("note", ""),
            period=raw.get("period", ""),
            alternates=[cls.from_raw(a) for a in raw.get("alternates", [])],
        )


def _values(owner: str, raw: dict) -> dict[str, CitedValue]:
    out = {}
    for cid, v in raw.items():
        if cid not in BY_ID:
            raise ValueError(f"{owner}: unknown criterion {cid!r}")
        out[cid] = CitedValue.from_raw(v)
    return out


@dataclass
class Insurer:
    id: str
    name: str
    kind: str
    metrics: dict[str, CitedValue]

    @classmethod
    def from_dict(cls, d: dict) -> Insurer:
        return cls(d["id"], d["name"], d["kind"], _values(d["id"], d.get("metrics", {})))


@dataclass
class Plan:
    id: str
    insurer: str
    name: str
    values: dict[str, CitedValue]
    insurer_id: str = ""
    variant: str = ""
    uin: str = ""
    sum_insured_options: list[int] = field(default_factory=list)
    documents: dict[str, str] = field(default_factory=dict)  # doc type -> official URL
    highlights: list[str] = field(default_factory=list)
    premium_by_age: dict[int, int] = field(default_factory=dict)  # band lower bound -> annual premium per member
    premium_basis: str = ""  # SI / zone / variant the premium table is for
    floater_discount_pct: float = 0.0
    zone: str | None = None  # pricing zone bought, if the plan prices by city
    zone_cities: dict[str, str] = field(default_factory=dict)
    network_hospitals: set[str] = field(default_factory=set)
    excluded_hospitals: set[str] = field(default_factory=set)
    sum_insured: int = 10_00_000  # SI being evaluated; set per user

    def get(self, criterion_id: str) -> object:
        cv = self.values.get(criterion_id)
        return None if cv is None else cv.value

    def label(self) -> str:
        v = f" {self.variant}" if self.variant else ""
        return f"{self.insurer} {self.name}{v}"

    @classmethod
    def from_dict(cls, d: dict) -> Plan:
        return cls(
            id=d["id"],
            insurer=d["insurer"],
            name=d["name"],
            values=_values(d["id"], d.get("values", {})),
            insurer_id=d.get("insurer_id", ""),
            variant=d.get("variant", ""),
            uin=d.get("uin", ""),
            sum_insured_options=d.get("sum_insured_options", []),
            documents=d.get("documents", {}),
            highlights=d.get("highlights", []),
            premium_by_age={int(k): v for k, v in d.get("premium_by_age", {}).items()},
            premium_basis=d.get("premium_basis", ""),
            floater_discount_pct=d.get("floater_discount_pct", 0.0),
            zone=d.get("zone"),
            zone_cities={k.lower(): v for k, v in d.get("zone_cities", {}).items()},
            network_hospitals=set(d.get("network_hospitals", [])),
            excluded_hospitals=set(d.get("excluded_hospitals", [])),
        )


def load_insurers(path: str | Path) -> dict[str, Insurer]:
    data = json.loads(Path(path).read_text())
    return {i["id"]: Insurer.from_dict(i) for i in data["insurers"]}


def load_plans(path: str | Path, insurers: dict[str, Insurer] | None = None) -> list[Plan]:
    """Load plans, merging each insurer's track-record metrics into its plans."""
    data = json.loads(Path(path).read_text())
    plans = [Plan.from_dict(p) for p in data["plans"]]
    for p in plans:
        ins = (insurers or {}).get(p.insurer_id)
        if ins:
            for cid, cv in ins.metrics.items():
                p.values.setdefault(cid, cv)
            p.values.setdefault("insurer_type", CitedValue(ins.kind, note="From insurer registry"))
    return plans


@dataclass
class Member:
    name: str
    age: int
    conditions: list[str] = field(default_factory=list)  # pre-existing diseases
    planning_pregnancy: bool = False
    is_parent: bool = False  # user's parent; usually better on a separate policy


@dataclass
class DealBreakers:
    no_room_rent_cap: bool = False
    no_copay: bool = False
    no_disease_sublimits: bool = False
    max_ped_wait_months: int | None = None
    need_maternity: bool = False
    preferred_hospitals_cashless: bool = False
    min_csr_amount: float | None = None
    max_premium: int | None = None


@dataclass
class UserProfile:
    members: list[Member]
    city: str = "Mumbai"  # where treatment is likely
    sum_insured: int = 10_00_000
    preferred_hospitals: list[str] = field(default_factory=list)
    priorities: dict[Category, int] = field(default_factory=dict)  # 0..5, default 3
    deal_breakers: DealBreakers = field(default_factory=DealBreakers)
    employer_cover: int = 0  # group cover from employer; ends when the job ends
    old_tax_regime: bool = False  # Section 80D is only available under the old regime
    tax_slab_pct: float = 30.0

    def zone_for(self, plan: Plan) -> str:
        return zone_for_city(self.city, plan.zone_cities)

    @property
    def oldest(self) -> int:
        return max(m.age for m in self.members)

    @property
    def has_ped(self) -> bool:
        return any(m.conditions for m in self.members)

    @property
    def planning_pregnancy(self) -> bool:
        return any(m.planning_pregnancy for m in self.members)

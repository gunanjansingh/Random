# CoverCompare (India)

Compare Indian health insurance plans on the fine print that decides whether a
claim is paid, not just on premium and sum insured. Answer a few questions
about your family, city, health conditions and deal-breakers, and get the top
plans side by side, with personal warnings and a claim simulator.

```
python3 -m healthcompare --demo     # canned profile
python3 -m healthcompare            # interactive questionnaire
python3 -m unittest discover -s tests -t .
```

No dependencies for the comparison app (Python 3.10+). The ingestion pipeline
needs `pip install pypdf anthropic`.

## What it compares

95 criteria in 10 groups (`healthcompare/criteria.py`), each with why it
matters. Those that commonly cause **claim rejections or deductions** are
flagged, for example:

- Room-rent caps and **proportionate deduction** (exceed the cap and the whole bill is cut)
- Co-pays: general, age-based, **zone-based**, non-network
- Disease sub-limits, modern-treatment caps, consumables/non-payables
- PED, specific-illness, personal and maternity waiting periods; moratorium; look-back
- Restoration rules (same illness? partial or full exhaustion?), bonus that shrinks after a claim
- Intimation deadlines, the "hospital" bed-count definition, excluded hospitals
- Insurer track record: claim settlement ratio, incurred claim ratio, complaints per 10k claims

## Plans covered

HDFC ERGO Optima Secure · Niva Bupa ReAssure 2.0 · Care Supreme ·
ICICI Lombard Elevate · Aditya Birla Activ One MAX · Star Super Star ·
Tata AIG MediCare Premier · ManipalCigna Sarvah Param ·
Bajaj Health Guard Gold / Silver

Every value links to its source. Most are still **unverified seed data**
gathered by web search: see `docs/DESIGN.md` §3.1 for exactly what that
means. Run the ingestion pipeline to verify values against the policy
wordings. Not financial advice: always read the policy wording and your
policy schedule before buying.

See [`docs/DESIGN.md`](docs/DESIGN.md) for the architecture and
[`docs/OPEN_QUESTIONS.md`](docs/OPEN_QUESTIONS.md) for decisions needed before launch
(including IRDAI rules on ranking insurance products).

# CoverCompare — Health Insurance Deep Comparison

> Goal: collect **every meaningful data point** about the top health insurance
> plans, including the fine-print items that cause claims to be rejected or
> reduced, then rank the top contenders against **the user's own criteria**.

Market: **India only** (IRDAI-regulated retail health insurance). IRDAI limits
(PED waiting ≤ 36 months, 60-month moratorium, lifelong renewal), city zones,
Section 80D, ₹ lakh/crore formatting and the insurer registry live in
`healthcompare/india.py`.

---

## 1. Why most comparison sites are not enough

Aggregators compare premium, sum insured, and a handful of headline features.
Claims, however, are rejected or cut on clauses people never read:

| What people compare | What actually decides the payout |
|---|---|
| Sum insured | Room-rent cap → **proportionate deduction** on the *whole bill* |
| "Covers pre-existing diseases" | PED waiting period, look-back definition, moratorium |
| Premium today | Premium at 60/70, age-band jumps, past portfolio hikes |
| "Restoration benefit" | Same illness or unrelated only? After first claim or only after SI is exhausted? |
| Claim settlement ratio | CSR by *amount*, repudiation %, complaints per 10k claims, TAT |
| Network hospitals (count) | Is *my* hospital in network? Zone co-pay if treated in a metro? |
| "Cashless" | Consumables/non-payables, intimation deadlines, documents |

The app's core asset is therefore the **criteria catalog**
(`healthcompare/criteria.py`). It currently lists 80+ criteria in 10
categories. Each criterion records why it matters and whether it is a
**rejection or deduction risk**.

---

## 2. Architecture

```
            ┌────────────────────────── INGESTION (offline, scheduled) ───────────────────────────┐
            │                                                                                    │
 Sources ──▶│ Fetch ──▶ Store raw (PDF/HTML, hashed, versioned) ──▶ Parse (PDF→text w/ pages)     │
            │                                                     │                              │
            │                                                     ▼                              │
            │                      Extract per criterion (rules + LLM, with quote + page cite)   │
            │                                                     │                              │
            │                                                     ▼                              │
            │      Reconcile across docs (precedence + conflict flags) ──▶ Human review queue    │
            └─────────────────────────────────────────────────────┬──────────────────────────────┘
                                                                  ▼
                                               Plan Knowledge Base (versioned JSON / Postgres)
                                                                  │
            ┌──────────────────────────── SERVING ────────────────▼──────────────────────────────┐
            │ Questionnaire ─▶ UserProfile ─▶ Hard filters ─▶ Weighted scoring ─▶ Personal gotchas│
            │                                                     │                              │
            │                                                     ▼                              │
            │                    Side-by-side comparison of top N, with source citations         │
            └────────────────────────────────────────────────────────────────────────────────────┘
```

### 2.1 Data sources (per insurer / per plan)

| Source | What we get | Notes |
|---|---|---|
| **Policy wording** (PDF, filed with IRDAI, has a UIN) | The legally binding definitions, exclusions, sub-limits, waiting periods | Highest precedence |
| **Customer Information Sheet (CIS)** | Standard-format summary of key terms | Good for cross-checking |
| **Prospectus / brochure** | Features, add-ons, sometimes premium tables | Marketing. Lowest precedence |
| **Premium chart / online quote** | Premium by age band, SI, zone, tenure | Quote forms may need a headless browser |
| **IRDAI Annual Report & handbook** | Claim settlement ratio (number & amount), incurred claim ratio, repudiation | Insurer-level, yearly |
| **Insurer public disclosures (NL forms)** | Claims ageing, grievances, solvency | Quarterly |
| **Insurance Ombudsman annual reports** | Complaints and awards against each insurer | Insurer-level |
| **Network hospital lists** | Cashless hospitals by city / pincode | Changes often. Re-scrape monthly |
| **Excluded / de-listed hospitals list** | Hospitals where claims are not paid | Often missed. High value |

Scraping rules: respect `robots.txt` and terms of use, rate-limit, cache by
content hash, and keep the raw file and its URL/date for every extracted value.

### 2.2 Extraction

Every plan value is stored as a **cited fact**:

```json
{
  "criterion": "room_rent_limit",
  "value": "1% of SI per day",
  "source": {"doc": "policy_wording", "uin": "XXXHLIP00000V012345", "page": 7,
             "quote": "Room rent up to 1% of Sum Insured per day..."},
  "confidence": 0.92,
  "verified_by": null
}
```

1. **Rule extractors** handle formulaic items (UIN, waiting periods in months, % co-pay).
2. **LLM extractor** handles everything else. Feed it one criterion group and
   the relevant chunks, and require JSON plus a verbatim quote and page.
   Reject any answer whose quote is not actually in the document.
3. **Reconciliation** order: policy wording > CIS > prospectus > brochure > website.
   If sources disagree, flag the conflict and send it to human review.
4. **Human review**: values with low confidence, conflicts, or rejection-risk
   flags must be verified before publishing.
5. **Change detection**: re-fetch on a schedule. A new hash triggers
   re-extraction and a diff ("Insurer X raised co-pay from 10% to 20% for 61+").

### 2.3 Serving: matching the user

1. **Questionnaire** → `UserProfile`: members and ages, city/zone, pre-existing
   conditions, planned pregnancy, budget, preferred hospitals, room
   preference, existing cover/employer cover, and priorities.
2. **Hard filters** (deal-breakers chosen by the user): e.g. "no room-rent
   cap", "no co-pay", "PED covered within 2 years", "my hospital must be
   cashless", "premium ≤ budget", "maternity covered".
3. **Weighted scoring**: each criterion is normalised to 0–1 against absolute
   best and worst bounds, not relative to the other plans, so scores mean the
   same thing across sessions. Weight = criterion default weight ×
   category priority set by the user × profile boosts (for example, a diabetic
   user gets PED weights ×3).
4. **Personal gotchas**: rules that turn fine print into warnings for this
   user, e.g. *"You are 58. This plan adds 20% co-pay from 61, which is 3
   renewals away."*
5. **Comparison view**: top N plans side by side. Every cell links to its
   quote and page in the source document. Missing data is shown as
   **Unknown – ask insurer**, never as a silent zero.

### 2.4 Ideas for later

- **Claim simulator**: "₹4L knee replacement at hospital X in a ₹8k/day room".
  Apply room-rent proportionate deduction, sub-limits, co-pay, consumables and
  deductible to show the actual payout per plan. This is the most persuasive
  feature for users.
- **Policy-wording diff** across years and plans.
- **Upload your existing policy PDF** → run the same extractor and get gotchas
  plus suggested upgrades or portability options.
- **Crowd-sourced claim experiences** (moderated) by insurer × hospital.

---

## 3. What is in this repo

| Path | What |
|---|---|
| `healthcompare/criteria.py` | The criteria catalog (95 criteria): the core asset |
| `healthcompare/india.py` | IRDAI rules, zones, Section 80D, ₹ formatting, insurer registry |
| `healthcompare/models.py` | Plans and insurers with cited values, user profile, deal-breakers |
| `healthcompare/engine.py` | Hard filters, scoring with ranges, personal gotchas, claim simulator |
| `healthcompare/ingest/` | fetch → extract (regex + Claude) → quote validation → reconcile |
| `healthcompare/cli.py` | Questionnaire → ranked comparison of the top contenders |
| `data/india/plans.json` | 10 real plans: official document URLs, UINs, cited values |
| `data/india/insurers.json` | 9 insurers: FY2024-25 claim settlement, ICR, complaints |

### 3.1 Data status (honest version)

The seed dataset was collected with web search, because this build
environment cannot reach insurer sites directly. Every value has a source URL
and a quote, but is marked `verified: false` with a confidence score until
`python -m healthcompare.ingest` re-reads the policy wording and finds the
quote on the page.

Already visible in the seed data:

- Aggregators disagree on insurer metrics. ICICI Lombard's FY25 claim
  settlement ratio is 97.16% in one source and 83.65% in another, most likely
  because they use different definitions. Both are kept, and the app shows
  "sources disagree". The fix is to read IRDAI's Annual Report table directly.
- Search summaries sometimes return a *definition* ("up to 36 months") in
  place of the plan's *value*. Quote validation against the PDF exists to
  catch this.
- Premiums: 52 indicative figures for 9 plans, each for a stated reference
  profile (ages, members, sum insured, city), taken from broker reviews,
  aggregators and insurer illustrations. They were adversarially checked;
  4 refuted figures were dropped. Most are single-source and low confidence.
  The engine never rescales a figure to the user's profile. It shows the
  nearest profile (age gap ≤ 10 years) plus a like-for-like row.
- Insurer CSR uses one definition for every insurer (a broker's computation
  from public disclosures) until IRDAI's own tables can be read. See
  `docs/OPEN_QUESTIONS.md` §D for what fact-checking changed.

### 3.2 Scoring under incomplete data

Unknown criteria score neutral (0.5). Treating them as bad would rank plans by
how much we happened to extract, not by how good they are. Each value is
pulled toward neutral in proportion to its confidence. Every score shows a
**possible range**: the score if every unknown turned out worst or best. The
CLI says plainly when the top plans' ranges overlap, which means the order is
not yet decisive.

### 3.3 Running ingestion

```
pip install pypdf anthropic          # plus ANTHROPIC_API_KEY or `ant auth login`
python -m healthcompare.ingest fetch     # robots.txt-aware, 2s/host delay, sha256 manifest
python -m healthcompare.ingest extract   # regex rules + Claude reading the PDF
python -m healthcompare.ingest apply     # merge into data/india/plans.json
```

`extract` keeps a value only if its quote is found on the cited PDF page
(±1 page) in text extracted locally with pypdf. When the regex rules and
Claude agree on a value, its confidence rises. `apply` lets the most
authoritative document win (policy wording > CIS > prospectus > brochure >
product page > secondary). It keeps disagreeing values as `alternates` and
marks a value `verified` only when its quote came from a filed document.
`fetch` flags documents whose hash changed since the last run. That is the
hook for "Insurer X changed its wording" alerts.

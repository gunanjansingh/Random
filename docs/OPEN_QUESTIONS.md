# Open questions for the product owner

Decisions only you can make, each with a recommended default so work can
continue if you're happy with it. **Blocking** items gate any public launch.
The regulatory facts below were fact-checked against press and legal sources
(Oct 2026). They are not legal advice; get counsel to confirm.

---

## A. Blocking

### A1. Regulatory route: can we rank plans at all?
**Verified facts**
- The IRDAI (Insurance Web Aggregators) Regulations 2017 (Reg. 42) say a web
  aggregator "shall not display ratings, rankings, endorsements or
  bestsellers", must keep content "unbiased and factual", and must "desist
  from commenting on insurers or their products". This is a flat ban. There
  is no exception for publishing your criteria.
- IRDAI fined Policybazaar ₹5 crore (order dated 4 Aug 2025). One of the
  penalised charges was showing plans as "Top"/"Best" without a disclosed
  basis; its health "Top plans" section featured 12 of 23 partner insurers.
- Comparison becomes a regulated activity once leads, sales or insurer money
  are involved. Brokers and corporate agents have their own regulations, and
  I haven't checked them for an equivalent ban.

**Why it matters:** the CLI currently prints "Top 3 for you", a "Match score
/100", and warnings that name insurers' clauses.

**Options**
- (a) Information-only site: no leads, no insurer money, neutral wording.
- (b) Operate under a licensed broker or corporate-agent partner.
- (c) Get your own IRDAI registration (web aggregator or broker).

**Recommended:** stay private and get an insurance-regulatory lawyer's opinion
now. If launching sooner, do (a). Replace "Top 3"/"score" with "Plans that fit
your criteria", show every eligible plan, and publish the methodology.

### A2. Business model
Free, ads, referral fees via a licensed partner, commission as an
intermediary, a paid fee-only report, or B2B data licensing.

**Why it matters:** any insurer or broker money pulls you into licensing
(A1). It also undercuts the "honest fine print" pitch unless disclosed on
every page.

**Recommended:** take no insurer or broker money until counsel signs off;
after that, a broker partnership with disclosed compensation.

### A3. Who is v1 for?
Families buying a first base plan, people buying for senior parents, people
porting or upgrading (upload your policy PDF), or advisors (B2B).

**Why it matters:** this sets the questionnaire, the plan scope (senior plans,
super top-ups) and how you stand apart from Ditto, Beshak, Nyvo and
Policybazaar, some of which already publish fine-print reviews.

**Recommended:** retail families (self, spouse, kids, plus a separate policy
for parents) buying or porting a base plan, launched as an invite-only beta.

### A4. Data sourcing rights
**Today's sources**
- Most premium figures (52 figures, 9 plans) and the CSR figures come from
  **joinditto.in, a registered broker and therefore a competitor**.
- The rest come from nyvo.in, a social-media post, press articles, and
  insurer marketing pages.
- Policybazaar quotes sit behind a mobile-number lead form, so scraping them
  creates fake leads, and their terms forbid it. I did **not** scrape them.

**Recommended:** use only primary public sources. That means insurer filed
documents (policy wording, CIS and prospectus, which often contain premium
tables), the IRDAI Annual Report and the insurers' NL public disclosures.
Treat competitor figures as temporary placeholders. Approach 2-3 insurers or
a broker for rate data, and watch Bima Sugam.

### A5. Users' health data (DPDP Act)
**Verified:** the DPDP Rules 2025 were notified on 13 Nov 2025. Notice,
consent, security safeguards, breach notification and verifiable parental
consent apply from **13 May 2027**. MeitY has proposed pulling this forward to
about 13 Nov 2026, but that had not been notified as of Sept 2026.

**Why it matters:** the questionnaire collects health conditions, pregnancy
plans and children's data for several family members.

**Recommended:** run v1 stateless. Use no names, store no health answers on a
server, share nothing with third parties, and draft a DPDP notice now.

### A6. Infrastructure and budget
**Why it matters:** this build environment can't reach any insurer site,
irdai.gov.in, Policybazaar or Ditto, so no value has been verified yet. Web
search is also capped at 200 calls per turn, which cut short the Bajaj
premium and IRDAI-metrics searches.

**Needed from you:**
- Where ingestion runs: your machine, a cloud VM or a scheduled CI job with
  open network access.
- An Anthropic API key.
- A monthly spend cap.
- Or widen this environment's network access: cloud environment menu → Edit
  → Network access.

**Recommended:** a 2-plan pilot run of `python -m healthcompare.ingest` to
measure the cost per document.

---

## B. Important, not blocking

| # | Question | Recommended default |
|---|---|---|
| B1 | **How opinionated?** Neutral table, user-weighted fit score (current), or editorial picks? Should price count in the score? | User-weighted fit with a public methodology and visible ranges. Price shown but not scored. Advice-like tips (separate policy for parents, 80D) worded as general information. |
| B2 | **Insurer metrics: which definition is canonical?** Sources disagree badly. ICICI Lombard is 83.65% (Ditto's formula) vs 97.16% (social post). Star Health's 99.06% turned out to be a "settled within 3 months" figure; its CSR is ~88.34%. | One definition for every insurer. Today that's Ditto's computation from public disclosures, as a placeholder. Then switch to IRDAI Annual Report tables. Score only metrics available for every insurer. |
| B3 | **Plan types in v1**: base indemnity only, plus Arogya Sanjeevani, super top-ups, senior plans, group cover, OPD, critical illness? | Base indemnity plus Arogya Sanjeevani as a benchmark. Super top-ups in v2. The scorer treats deductibles as bad, which would need inverting for top-ups. |
| B4 | **Which insurers, plans and versions?** 10 plans from 9 insurers today. Missing: SBI General, Digit, Reliance, Galaxy, Narayana, the 4 PSUs, Royal Sundaram, IFFCO Tokio, Chola MS, Acko, Navi and more. **Niva Bupa ReAssure 3.0** (launched 26 Aug 2025) is a separate product sold *alongside* ReAssure 2.0, with tiered room eligibility. | Top 12-15 insurers by retail health premium, current flagship plans, each variant modelled separately. Add ReAssure 3.0. |
| B5 | **Add-ons**: compare base plans only, or as configured? Care's consumables cover, ICICI's Room Modifier and the PED buy-downs all change key terms and price. | Score the base plan, show add-ons as notes now, and add user-toggleable add-ons later. |
| B6 | **Premiums**: (a) none, (b) indicative public figures (current), (c) prospectus rate tables, (d) live quotes (needs a licence), (e) user pastes a quote? | (c) where prospectus tables exist, else (b) labelled "indicative, not a quote". Live quotes only after A1. |
| B7 | **Unknown data**: a value isn't known for a deal-breaker the user set. Hide the plan, show it as "can't confirm", or treat it as passing (current)? | Show as "can't confirm", sorted below confirmed passes. Publish a plan only after its weight-4/5 rejection-risk fields are human-verified. |
| B8 | **Who verifies?** Today "verified" means the quote string-matched in a filed document, with no human review. Who reviews flagged values, and how often is data refreshed? | Two statuses: machine-matched and human-reviewed. A part-time ex-claims or underwriting reviewer. Monthly document re-fetch, yearly IRDAI metrics, and a public "report an error" link. |
| B9 | **Questionnaire defaults**: "No room cap" and "No co-pay" default to *yes* and silently drop plans. Conditions are free text. | Deal-breakers default off. A fixed condition checklist (diabetes, BP, thyroid, asthma, cardiac, cancer history, other). Suggest a sum insured by city and family size. |
| B10 | **Claim simulator**: ship it? It uses one fixed scenario and rough cost assumptions. **Verified:** the 2020 IRDAI proportionate-deduction rules (consolidated in 2024) exempt ICU, pharmacy, consumables, implants, medical devices and diagnostics, and hospitals without room-category billing. Deduction still applies to doctor, OT and nursing fees billed by room category. | Ship with a user-editable scenario showing best and worst cases, after an expert reviews the logic. Use dated hospital tariff benchmarks. |
| B11 | **Hospital networks**: collect per-insurer network and excluded-hospital lists? | Defer to v2 and hide the feature. Key hospitals by IRDAI ROHINI ID when built. |
| B12 | **Platform and languages** | A mobile-first web app in English, with Hindi next. Keep the CLI for QA. |
| B13 | **Repo, name, PR**: the code lives in `gunanjansingh/Random` on a feature branch. "CoverCompare" is a placeholder. | Move it to a private `covercompare` repo, run a trademark and domain check, and open a PR for your review. |

---

## C. Assumptions baked into the code: please confirm or replace

| Where | Assumption | Risk if wrong |
|---|---|---|
| `engine.py` `TYPICAL_PRIVATE_ROOM` | Private room ₹8k / ₹6k / ₹4k per day in Zones A / B / C | Room-cap warnings shown to users as fact, with no source |
| `engine.py` `ClaimScenario` | Consumables are 8% of a bill. 30% of a bill is exempt from proportionate deduction. One scenario: ₹5L bill, ₹8k room, 5 days | Simulator payouts are illustrative only |
| `engine.py` `weights_for` | PED weights ×3 if any condition; maternity ×3 or ×0.1; "senior" weights ×2.5 from age **50** (`india.SENIOR_AGE` is 60) | These multipliers drive the ranking |
| `criteria.py` weights | 1-5 importance per criterion; 29 of 95 flagged as rejection risks | The ranking reflects our opinion (see A1, B1) |
| `criteria.py` | `insurer_type` order: standalone health > private general > PSU. Publishing an excluded-hospital list scores as *bad* | Editorial judgements about named insurer categories |
| `india.py` zones | Delhi NCR, Mumbai and Gujarat metros are Zone A; Bengaluru, Chennai, Hyderabad, Kolkata, Pune etc. are Zone B; everything else is C | Each insurer has its own zone list |
| `india.py` 80D | ₹25k / ₹50k limits; tax saved = deduction × slab × 1.04; old regime only; the parents' premium is never passed in | Mis-stated tax savings, and a tax-advice look |
| `engine.py` premiums | Nearest reference profile; nothing shown beyond a 10-year age gap; never rescaled; the budget filter applies only to close matches | Ignores zone and age-band jumps |
| `data/india/plans.json` | `lifelong_renewal = true` for all plans, inferred from regulation, not from each wording | A plan-specific claim made from a general rule |

---

## D. What the fact-check changed

- **Star Health's CSR** was 99.06% (social post). It's ~88.34% on the
  standard definition. The 99.06% matches a "settled within 3 months" figure.
- **ICICI Lombard's CSR** conflict is resolved by definition: 83.65%
  (standard) vs 97.16% (unclear definition). Both are kept, and the app shows
  "sources disagree".
- **ICR figures** are now traced to the IRDAI Annual Report 2024-25 via
  Business Standard. ICR is now scored as a healthy band (65-90%), so a
  loss-making insurer no longer gets full marks.
- **4 premium figures were refuted** and excluded. Two were site-wide
  marketing floors, one was the wrong plan variant, and one was an outlier
  chart.
- **Bajaj Health Guard Silver** appears to be sold only at about ₹1.5-2L
  cover (not yet confirmed), where its 1% room cap means ₹2,000 a day.

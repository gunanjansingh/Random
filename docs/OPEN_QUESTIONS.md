# Open questions for the product owner

Decisions only you can make, each with a recommended default so work can
continue in the meantime.

---

## Decided (7 Oct 2026)

| Topic | Decision |
|---|---|
| Positioning | **Information only** for now, to help people make an informed decision. IRDAI registration will come later. |
| How results are framed | No "best plan" labels. The user answers questions and sets filters; the plans left are shown as *"Based on our conversation and your filters, this is the best-suited plan for you"*, **with the reasons and supporting data**. Each reason states the filters passed (with the plan's actual value), its strengths on what the user said matters, its trade-offs, and its source. Close calls are called close. |
| Data for premiums | Use the **insurers' own filed documents** (prospectus or premium chart) as the source of premium tables. |
| v1 (MVP) | **Stateless**: nothing about the user is stored. |
| Regulation research | Not needed now. |

## Deferred

- **Business model**: revisit once the MVP works. *(I'll ask again then.)*
- **Section B** below: discuss later.

## Still open

### A3. Who is v1 for?
Families buying a first base plan, people buying for senior parents, people
porting or upgrading, or advisors.

**Recommended:** retail families (self, spouse, kids, plus a separate policy
for parents), shared with a small group of testers first.

### A6. Document access: **resolved** (network access enabled 7 Oct 2026)
Documents are downloaded and read. What's left:
- **ICICI Lombard** blocks automated downloads. To include it, download these two
  PDFs in a browser and share them:
  [prospectus](https://www.icicilombard.com/docs/default-source/default-document-library/elevate-prospectus_.pdf),
  [policy wording](https://www.icicilombard.com/docs/default-source/default-document-library/elevate.pdf).
- **Care Supreme** and **Activ One** current policy wordings aren't online, so the
  current prospectus and CIS were used instead.
- An Anthropic API key is **not needed for the MVP**. Extraction was done
  in-session; a key only matters for automated monthly refreshes later.

---

## B. Important, not blocking (deferred: discuss later)

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

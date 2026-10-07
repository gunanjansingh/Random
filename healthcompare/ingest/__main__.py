"""python -m healthcompare.ingest {fetch,extract,apply} [--plan ID] [--no-claude]"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..criteria import CRITERIA, Source
from .fetch import fetch_all

ROOT = Path(__file__).resolve().parents[2]
PLANS = ROOT / "data" / "india" / "plans.json"
CACHE = ROOT / ".cache" / "documents"
EXTRACTED = ROOT / ".cache" / "extracted.json"

# Insurer metrics (CSR, complaints...) come from IRDAI data, not plan documents.
DOC_CRITERIA = [c for c in CRITERIA if {Source.POLICY_WORDING, Source.CIS, Source.PROSPECTUS, Source.BROCHURE} & set(c.sources)]
EXTRACTABLE_DOCS = ("policy_wording", "customer_information_sheet", "prospectus", "brochure")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m healthcompare.ingest")
    ap.add_argument("step", choices=["fetch", "extract", "apply"])
    ap.add_argument("--plan", help="limit to one plan id")
    ap.add_argument("--no-claude", action="store_true", help="regex rules only (no API calls)")
    args = ap.parse_args(argv)

    if args.step == "fetch":
        for r in fetch_all(PLANS, CACHE, args.plan):
            flag = " (CHANGED since last fetch)" if r.get("changed") else ""
            print(f"{r['status']:>20}  {r['plan_id']}/{r['doc_type']}{flag}")
        return

    if args.step == "extract":
        from .extract import extract_document

        manifest = json.loads((CACHE / "manifest.json").read_text())
        plans = {p["id"]: p for p in json.loads(PLANS.read_text())["plans"]}
        results = json.loads(EXTRACTED.read_text()) if EXTRACTED.exists() else {}
        for key, entry in manifest.items():
            plan_id, doc_type = key.split("/", 1)
            if (args.plan and plan_id != args.plan) or entry.get("status") != "ok" \
                    or doc_type not in EXTRACTABLE_DOCS or not entry["path"].endswith(".pdf"):
                continue
            p = plans[plan_id]
            name = f"{p['insurer']} {p['name']} {p.get('variant', '')}".strip()
            res = extract_document(CACHE / entry["path"], name, doc_type, use_claude=not args.no_claude,
                                   criteria=DOC_CRITERIA)
            docs = [d for d in results.get(plan_id, []) if d["doc_type"] != doc_type]
            results[plan_id] = docs + [res]
            print(f"{key}: {len(res['candidates'])} validated values, {res['dropped']} dropped (quote not found)")
        EXTRACTED.write_text(json.dumps(results, indent=1))
        return

    from .reconcile import apply_extractions

    doc = json.loads(PLANS.read_text())
    changed = apply_extractions(doc, json.loads(EXTRACTED.read_text()))
    PLANS.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    for plan_id, n in changed.items():
        print(f"{plan_id}: {n} values updated")


if __name__ == "__main__":
    main()

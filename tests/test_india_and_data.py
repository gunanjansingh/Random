import json
import unittest
from pathlib import Path

from healthcompare import india
from healthcompare.criteria import BY_ID
from healthcompare.models import SOURCE_PRECEDENCE, load_insurers, load_plans

DATA = Path(__file__).resolve().parent.parent / "data" / "india"


class IndiaHelpers(unittest.TestCase):
    def test_inr_formatting(self):
        self.assertEqual(india.inr(500000), "Rs 5L")
        self.assertEqual(india.inr(1234567), "Rs 12,34,567")
        self.assertEqual(india.inr(25000), "Rs 25,000")
        self.assertEqual(india.inr(1_00_00_000), "Rs 1Cr")

    def test_80d_limits(self):
        self.assertEqual(india.section_80d_deduction(40_000), 25_000)
        self.assertEqual(india.section_80d_deduction(40_000, self_or_spouse_senior=True), 40_000)
        self.assertEqual(india.section_80d_deduction(20_000, parents_premium=60_000, parents_senior=True), 70_000)

    def test_zone_lookup_prefers_plan_list(self):
        self.assertEqual(india.zone_for_city("Mumbai"), "A")
        self.assertEqual(india.zone_for_city("Patna"), "C")
        self.assertEqual(india.zone_for_city("Pune", {"pune": "A"}), "A")

    def test_irdai_violations(self):
        msgs = [v.criterion for v in india.irdai_violations({"ped_waiting_months": 48, "lifelong_renewal": False})]
        self.assertEqual(msgs, ["ped_waiting_months", "lifelong_renewal"])


class RealDataset(unittest.TestCase):
    """Guards on data/india: every value must be traceable to a source."""

    @classmethod
    def setUpClass(cls):
        cls.insurers = load_insurers(DATA / "insurers.json")
        cls.plans = load_plans(DATA / "plans.json", cls.insurers)
        cls.raw = json.loads((DATA / "plans.json").read_text())["plans"]

    def test_every_plan_links_to_a_known_insurer_and_official_document(self):
        for p in self.plans:
            self.assertIn(p.insurer_id, self.insurers, p.id)
            self.assertTrue(p.documents, f"{p.id} has no source documents")

    def test_every_value_is_cited_and_typed(self):
        for p in self.raw:
            for cid, v in p["values"].items():
                with self.subTest(plan=p["id"], criterion=cid):
                    self.assertIn("citation", v)
                    self.assertTrue(v["citation"]["url"].startswith("https://"))
                    self.assertIn(v["citation"]["source"], SOURCE_PRECEDENCE)
                    if BY_ID[cid].kind.value != "text":
                        self.assertIsNotNone(BY_ID[cid].score(v["value"]), "value does not fit criterion type")

    def test_no_value_claims_verification_without_pipeline(self):
        # Flip only via `python -m healthcompare.ingest apply`, which validates quotes.
        for p in self.raw:
            for cid, v in p["values"].items():
                if v["verified"]:
                    self.assertIn("page", v["citation"], f"{p['id']}.{cid} verified without a page reference")

    def test_dataset_passes_irdai_sanity_checks(self):
        for p in self.plans:
            with self.subTest(plan=p.id):
                self.assertEqual(india.irdai_violations({k: v.value for k, v in p.values.items()}), [])


if __name__ == "__main__":
    unittest.main()

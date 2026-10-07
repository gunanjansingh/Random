import json
import unittest

from healthcompare.ingest.extract import Candidate, parse_response, rule_candidates, validate
from healthcompare.ingest.reconcile import apply_extractions, merge_value

PAGES = [
    "Product Name: Test Plan UIN: NBHHLIP27054V032627",
    "Expenses related to the treatment of a Pre-existing Disease (PED) and its direct complications shall be "
    "excluded until the expiry of 36 months of continuous coverage after the date of inception of the first Policy.",
    "Expenses related to the treatment of any Illness within 30 days from the first Policy commencement date shall be excluded.",
]


class Extraction(unittest.TestCase):
    def test_rules_find_waiting_periods_and_uin(self):
        cands, uins = rule_candidates(PAGES)
        got = {c.criterion: (c.value, c.page) for c in cands}
        self.assertEqual(got["ped_waiting_months"], (36, 2))
        self.assertEqual(got["initial_waiting_days"], (30, 3))
        self.assertEqual(uins, {"NBHHLIP27054V032627"})

    def test_quote_validation_rejects_invented_quotes(self):
        real = Candidate("ped_waiting_months", 36, "excluded until the expiry of 36 months of continuous coverage", 2, 0.9, "claude")
        fake = Candidate("ped_waiting_months", 24, "excluded until the expiry of 24 months of continuous coverage", 2, 0.9, "claude")
        wrong_page = Candidate("ped_waiting_months", 36, "excluded until the expiry of 36 months of continuous coverage", 9, 0.9, "claude")
        self.assertTrue(validate(real, PAGES))
        self.assertFalse(validate(fake, PAGES))
        self.assertFalse(validate(wrong_page, PAGES))

    def test_parse_response_coerces_and_drops_bad_values(self):
        text = json.dumps({"values": [
            {"criterion": "ped_waiting_months", "value": "36", "quote": "q", "page": 2, "confidence": 0.9, "note": ""},
            {"criterion": "room_rent_limit", "value": "palace_suite", "quote": "q", "page": 1, "confidence": 0.9, "note": ""},
            {"criterion": "consumables_covered", "value": "false", "quote": "q", "page": 1, "confidence": 0.8, "note": "add-on"},
        ]})
        got = {c.criterion: c.value for c in parse_response(text)}
        self.assertEqual(got, {"ped_waiting_months": 36, "consumables_covered": False})


class Reconcile(unittest.TestCase):
    def test_policy_wording_beats_secondary_and_keeps_disagreement(self):
        old = {"value": 24, "confidence": 0.5, "verified": False, "citation": {"source": "secondary", "url": "https://x"}}
        new = {"value": 36, "confidence": 0.8, "verified": True, "citation": {"source": "policy_wording", "url": "https://y"}}
        merged = merge_value(old, new)
        self.assertEqual(merged["value"], 36)
        self.assertEqual([a["value"] for a in merged["alternates"]], [24])

    def test_apply_only_validated_and_marks_verified(self):
        doc = {"plans": [{"id": "p", "documents": {"policy_wording": "https://pw"}, "values": {}}]}
        ext = {"p": [{"doc_type": "policy_wording", "uins": ["ABCDEHLIP12345V012345"], "candidates": [
            {"criterion": "ped_waiting_months", "value": 36, "quote": "q", "page": 2, "confidence": 0.9, "validated": True},
            {"criterion": "post_hosp_days", "value": 180, "quote": "q", "page": 3, "confidence": 0.9, "validated": False},
        ]}]}
        apply_extractions(doc, ext)
        p = doc["plans"][0]
        self.assertEqual(set(p["values"]), {"ped_waiting_months"})
        self.assertTrue(p["values"]["ped_waiting_months"]["verified"])
        self.assertEqual(p["uin"], "ABCDEHLIP12345V012345")


if __name__ == "__main__":
    unittest.main()


class NumberParsing(unittest.TestCase):
    def test_indian_amounts_and_units(self):
        from healthcompare.ingest.extract import _number
        self.assertEqual(_number("36"), 36)
        self.assertEqual(_number("36 months"), 36)
        self.assertEqual(_number("Rs 1 lakh"), 1_00_000)
        self.assertEqual(_number("₹1,50,000"), 1_50_000)
        self.assertEqual(_number("2 crore"), 2_00_00_000)
        self.assertEqual(_number("20%"), 20)

    def test_ranges_and_words_rejected(self):
        from healthcompare.ingest.extract import _number
        for bad in ("2-4", "up to 36", "thirty", "1 to 2 lakh"):
            with self.assertRaises(ValueError, msg=bad):
                _number(bad)


class MetricPrecedence(unittest.TestCase):
    def test_irdai_beats_product_page_for_insurer_metrics_only(self):
        page = {"value": 99, "confidence": 0.6, "verified": False, "citation": {"source": "product_page", "url": "https://a"}}
        irdai = {"value": 92, "confidence": 0.6, "verified": False, "citation": {"source": "irdai", "url": "https://b"}}
        self.assertEqual(merge_value(page, irdai, "csr_count")["value"], 92)
        self.assertEqual(merge_value(page, irdai, "room_rent_limit")["value"], 99)


class VersionGuard(unittest.TestCase):
    def test_document_from_another_version_is_not_applied(self):
        doc = {"plans": [{"id": "p", "uin": "NEWHLIP27001V032627", "documents": {"policy_wording": "https://pw"}, "values": {}}]}
        ext = {"p": [{"doc_type": "policy_wording", "uins": ["NEWHLIP25001V012425"], "uin_matches": False, "candidates": [
            {"criterion": "ped_waiting_months", "value": 48, "quote": "q", "page": 2, "confidence": 0.9, "validated": True}]}]}
        apply_extractions(doc, ext)
        self.assertEqual(doc["plans"][0]["values"], {})

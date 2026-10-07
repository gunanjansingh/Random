import unittest

from healthcompare.criteria import BY_ID
from healthcompare.engine import ClaimScenario, check_deal_breakers, gotchas, rank, score_plan, simulate_claim
from healthcompare.models import CitedValue, DealBreakers, Member, Plan, UserProfile


def plan(pid="p", **values) -> Plan:
    return Plan(id=pid, insurer="Test", name=pid, values={k: CitedValue(v, confidence=0.9) for k, v in values.items()})


def user(**kw) -> UserProfile:
    kw.setdefault("members", [Member("You", 34)])
    return UserProfile(**kw)


class CriterionScoring(unittest.TestCase):
    def test_number_bounds_work_in_both_directions(self):
        self.assertEqual(BY_ID["ped_waiting_months"].score(0), 1.0)  # lower is better
        self.assertEqual(BY_ID["ped_waiting_months"].score(36), 0.0)
        self.assertEqual(BY_ID["post_hosp_days"].score(180), 1.0)  # higher is better
        self.assertEqual(BY_ID["post_hosp_days"].score(500), 1.0)  # clamped

    def test_enum_and_bool(self):
        self.assertEqual(BY_ID["room_rent_limit"].score("no_limit"), 1.0)
        self.assertEqual(BY_ID["room_rent_limit"].score("1pct_si_per_day"), 0.0)
        self.assertIsNone(BY_ID["room_rent_limit"].score("made_up"))
        self.assertEqual(BY_ID["proportionate_deduction"].score(False), 1.0)


class DealBreakersTest(unittest.TestCase):
    def test_known_violation_fails_unknown_is_flagged(self):
        u = user(deal_breakers=DealBreakers(no_room_rent_cap=True, no_copay=True))
        r = check_deal_breakers(plan(room_rent_limit="1pct_si_per_day"), u)
        self.assertFalse(r.eligible)
        self.assertTrue(any("Co-pay" in x for x in r.unverified))

    def test_missing_premium_does_not_fail_budget(self):
        r = check_deal_breakers(plan(), user(deal_breakers=DealBreakers(max_premium=20000)))
        self.assertTrue(r.eligible)
        self.assertTrue(any("Premium" in x for x in r.unverified))

    def test_entry_age_limit(self):
        r = check_deal_breakers(plan(max_entry_age=65), user(members=[Member("Mom", 70)]))
        self.assertFalse(r.eligible)


class ScoringTest(unittest.TestCase):
    def test_better_terms_score_higher_and_range_brackets_total(self):
        good = plan("good", room_rent_limit="no_limit", general_copay_pct=0, ped_waiting_months=12)
        bad = plan("bad", room_rent_limit="1pct_si_per_day", proportionate_deduction=True, general_copay_pct=20, ped_waiting_months=36)
        u = user()
        g, b = score_plan(good, u), score_plan(bad, u)
        self.assertGreater(g.total, b.total)
        lo, hi = g.score_range
        self.assertLessEqual(lo, g.total)
        self.assertGreaterEqual(hi, g.total)

    def test_no_room_cap_implies_no_proportionate_deduction(self):
        card = score_plan(plan(room_rent_limit="no_limit"), user())
        self.assertIs(card.plan.get("proportionate_deduction"), False)

    def test_low_confidence_values_count_less(self):
        sure = Plan(id="a", insurer="T", name="a", values={"general_copay_pct": CitedValue(30, confidence=1.0)})
        unsure = Plan(id="b", insurer="T", name="b", values={"general_copay_pct": CitedValue(30, confidence=0.2)})
        self.assertLess(score_plan(sure, user()).total, score_plan(unsure, user()).total)

    def test_conflicting_sources_are_flagged(self):
        p = plan(csr_count=97.16)
        p.values["csr_count"].alternates = [CitedValue(83.65)]
        self.assertTrue(any("disagree" in x for x in score_plan(p, user()).to_verify))

    def test_rank_drops_ineligible(self):
        top, dropped = rank([plan("a", room_rent_limit="no_limit"), plan("b", room_rent_limit="shared_room")],
                            user(deal_breakers=DealBreakers(no_room_rent_cap=True)))
        self.assertEqual([c.plan.id for c in top], ["a"])
        self.assertEqual([c.plan.id for c in dropped], ["b"])


class GotchasTest(unittest.TestCase):
    def texts(self, p, u):
        return " | ".join(g.text for g in gotchas(p, u))

    def test_room_cap_warns_with_proportionate_deduction(self):
        u = user(city="Mumbai", sum_insured=5_00_000)
        t = self.texts(plan(room_rent_limit="1pct_si_per_day", proportionate_deduction=True), u)
        self.assertIn("proportionate deduction", t)

    def test_ped_waiting_named_for_member(self):
        u = user(members=[Member("You", 40, conditions=["diabetes"])])
        self.assertIn("Your diabetes not covered for the first 36 months", self.texts(plan(ped_waiting_months=36), u))

    def test_zone_copay_when_treated_in_costlier_zone(self):
        p = plan(zone_copay_pct=20)
        p.zone = "C"
        self.assertIn("Zone A", self.texts(p, user(city="Mumbai")))
        self.assertNotIn("Zone", self.texts(p, user(city="Patna")))

    def test_upcoming_age_copay(self):
        u = user(members=[Member("Dad", 58)])
        self.assertIn("3 years from now", self.texts(plan(age_copay_pct=20, age_copay_from_age=61), u))


class ClaimSimulatorTest(unittest.TestCase):
    def test_proportionate_deduction_cuts_whole_bill(self):
        p = plan(room_rent_limit="1pct_si_per_day", proportionate_deduction=True, consumables_covered=True)
        u = user(sum_insured=5_00_000)  # cap Rs 5,000/day
        paid, steps = simulate_claim(p, ClaimScenario(bill=3_00_000, room_rent_per_day=10_000, days=4, patient_age=40), u)
        names = [n for n, _ in steps]
        self.assertIn("Room rent above cap", names)
        self.assertTrue(any(n.startswith("Proportionate deduction (50% paid)") for n in names))
        self.assertLess(paid, 3_00_000 - 20_000)  # far more than just the room excess

    def test_no_limits_pays_in_full(self):
        p = plan(room_rent_limit="no_limit", consumables_covered=True, general_copay_pct=0)
        paid, steps = simulate_claim(p, ClaimScenario(bill=2_00_000, room_rent_per_day=9_000, days=3, patient_age=40), user())
        self.assertEqual((paid, steps), (2_00_000, []))

    def test_copay_and_sum_insured_cap(self):
        p = plan(general_copay_pct=10)
        paid, _ = simulate_claim(p, ClaimScenario(bill=20_00_000, room_rent_per_day=5_000, days=10, patient_age=40),
                                 user(sum_insured=10_00_000))
        self.assertEqual(paid, 10_00_000)


if __name__ == "__main__":
    unittest.main()


class ApproxPremiumTest(unittest.TestCase):
    def est(self, profile, members, ages, best, si=10_00_000):
        from healthcompare.models import PremiumEstimate
        return PremiumEstimate(profile, members, ages, si, "Metro", best - 1000, best + 1000, best, "ex-GST", "medium", ["https://x"])

    def setUp(self):
        self.p = plan()
        self.p.premium_estimates = [self.est("P30", "1A", [30], 12000), self.est("P45", "1A", [45], 20000),
                                    self.est("FAM", "2A+1C", [35, 32, 5], 30000)]

    def test_picks_matching_family_shape_and_age(self):
        from healthcompare.engine import approx_premium
        ap = approx_premium(self.p, user(members=[Member("You", 43)]))
        self.assertEqual((ap.estimate.profile, ap.close), ("P45", True))
        fam = approx_premium(self.p, user(members=[Member("A", 36), Member("B", 33), Member("C", 4)]))
        self.assertEqual((fam.estimate.profile, fam.close), ("FAM", True))

    def test_loose_match_is_flagged_not_rescaled(self):
        from healthcompare.engine import approx_premium
        ap = approx_premium(self.p, user(members=[Member("Dad", 53)]))
        self.assertFalse(ap.close)
        self.assertEqual(ap.estimate.best, 20000)

    def test_no_reference_price_when_ages_too_far_apart(self):
        from healthcompare.engine import approx_premium
        self.assertIsNone(approx_premium(self.p, user(members=[Member("Mom", 68)])))

    def test_age_outweighs_family_shape(self):
        from healthcompare.engine import approx_premium
        self.p.premium_estimates.append(self.est("SEN", "2A", [62, 60], 60000))
        ap = approx_premium(self.p, user(members=[Member("A", 34), Member("B", 32)]))
        self.assertNotEqual(ap.estimate.profile, "SEN")

    def test_budget_fails_only_on_close_match_above_low_end(self):
        r = check_deal_breakers(self.p, user(members=[Member("You", 30)], deal_breakers=DealBreakers(max_premium=9000)))
        self.assertFalse(r.eligible)
        r = check_deal_breakers(self.p, user(members=[Member("Mom", 68)], deal_breakers=DealBreakers(max_premium=9000)))
        self.assertTrue(r.eligible)


class FixesTest(unittest.TestCase):
    def test_icr_scored_as_a_band(self):
        icr = BY_ID["icr"]
        self.assertEqual(icr.score(80), 1.0)
        self.assertLess(icr.score(105), icr.score(88))  # loss-making insurer no longer gets full marks
        self.assertLess(icr.score(45), icr.score(70))

    def test_preferred_hospital_without_network_data_is_unverified_not_failed(self):
        u = user(preferred_hospitals=["Some Hospital"], deal_breakers=DealBreakers(preferred_hospitals_cashless=True))
        r = check_deal_breakers(plan(), u)
        self.assertTrue(r.eligible)
        self.assertTrue(any("Network" in x for x in r.unverified))

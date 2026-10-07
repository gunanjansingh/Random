import unittest

from healthcompare.models import CitedValue, CurrentPolicy, Member, Plan, UserProfile
from healthcompare.switching import analyse, current_plan


def plan(pid, **values):
    return Plan(id=pid, insurer="T", name=pid, values={k: CitedValue(v, confidence=0.9) for k, v in values.items()})


def user(cp, si=10_00_000, **kw):
    kw.setdefault("members", [Member("You", 35, conditions=["diabetes"])])
    return UserProfile(sum_insured=si, current_policy=cp, **kw)


class SwitchingTest(unittest.TestCase):
    def setUp(self):
        self.old = plan("old", room_rent_limit="1pct_si_per_day", ped_waiting_months=36, specific_disease_waiting_months=24,
                        premium_age_lock=True)
        self.new = plan("new", room_rent_limit="no_limit", ped_waiting_months=36, specific_disease_waiting_months=24)
        self.plans = [self.old, self.new]

    def texts(self, a, kind):
        return " | ".join(i.text for i in a.by_kind(kind))

    def test_staying_and_raising_cover(self):
        cp = CurrentPolicy(plan_id="old", sum_insured=5_00_000, continuous_years=4)
        a = analyse(self.old, cp, self.plans, user(cp))
        self.assertTrue(a.staying)
        self.assertIn("Raise cover", self.texts(a, "gain"))
        self.assertIn("extra Rs 5L of cover starts fresh waits", self.texts(a, "wait"))
        self.assertIn("already served", self.texts(a, "keeps"))

    def test_switching_shows_gains_losses_and_running_waits(self):
        cp = CurrentPolicy(plan_id="old", sum_insured=10_00_000, continuous_years=1)
        a = analyse(self.new, cp, self.plans, user(cp))
        self.assertFalse(a.staying)
        self.assertIn("Room rent limit", self.texts(a, "gain"))
        self.assertIn("locked entry-age premium", self.texts(a, "loss"))
        self.assertIn("Pre-existing disease (24 more months)", self.texts(a, "wait"))
        self.assertNotIn("extra", self.texts(a, "wait"))  # same cover: no fresh waits
        self.assertTrue(a.by_kind("caution"))

    def test_plan_not_in_our_list_is_built_from_answers(self):
        cp = CurrentPolicy(name="Old employer plan", sum_insured=3_00_000, continuous_years=2,
                           terms={"room_rent_limit": "single_private_room", "general_copay_pct": 20})
        cur = current_plan(cp, self.plans)
        self.assertEqual(cur.get("general_copay_pct"), 20)
        a = analyse(self.new, cp, self.plans, user(cp))
        self.assertIn("Room rent limit", self.texts(a, "gain"))


class ExtraCoverTest(unittest.TestCase):
    def test_staying_counts_base_increase_porting_counts_bonus(self):
        from healthcompare.switching import extra_cover
        cp = CurrentPolicy(sum_insured=5_00_000, cumulative_bonus=1_00_000)
        u = user(cp)
        self.assertEqual(extra_cover(cp, u, staying=True), 5_00_000)
        self.assertEqual(extra_cover(cp, u, staying=False), 4_00_000)

    def test_maternity_not_in_old_plan_gets_no_credit(self):
        old = plan("old", maternity_covered=False)
        new = plan("new", maternity_covered=True, maternity_waiting_months=24)
        cp = CurrentPolicy(plan_id="old", sum_insured=10_00_000, continuous_years=5)
        u = user(cp, members=[Member("You", 30, planning_pregnancy=True)])
        a = analyse(new, cp, [old, new], u)
        self.assertIn("Maternity (24 months, not covered by your current plan so no credit)", " ".join(i.text for i in a.by_kind("wait")))

    def test_migration_within_same_insurer(self):
        a1, a2 = plan("a1"), plan("a2")
        a1.insurer_id = a2.insurer_id = "ins"
        cp = CurrentPolicy(plan_id="a1", sum_insured=10_00_000, continuous_years=4)
        out = analyse(a2, cp, [a1, a2], user(cp))
        self.assertIn("migration", " ".join(i.text for i in out.by_kind("keeps")))
        self.assertFalse(any("Apply to the new insurer" in i.text for i in out.by_kind("caution")))

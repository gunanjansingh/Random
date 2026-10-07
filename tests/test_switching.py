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
        self.assertIn("Maternity is new cover for you", " ".join(i.text for i in a.by_kind("wait")))

    def test_migration_within_same_insurer(self):
        a1, a2 = plan("a1"), plan("a2")
        a1.insurer_id = a2.insurer_id = "ins"
        cp = CurrentPolicy(plan_id="a1", sum_insured=10_00_000, continuous_years=4)
        out = analyse(a2, cp, [a1, a2], user(cp))
        self.assertIn("migration", " ".join(i.text for i in out.by_kind("keeps")))
        self.assertFalse(any("Apply to the new insurer" in i.text for i in out.by_kind("caution")))


class ReviewFindings(unittest.TestCase):
    """Regression tests for the independent review of the switching feature."""

    def setUp(self):
        self.a1 = plan("a1", ped_waiting_months=36, specific_disease_waiting_months=24, initial_waiting_days=30)
        self.a2 = plan("a2", ped_waiting_months=36, specific_disease_waiting_months=24, initial_waiting_days=30)
        self.b = plan("b", ped_waiting_months=36, specific_disease_waiting_months=24, initial_waiting_days=30)
        self.a1.insurer_id = self.a2.insurer_id = "ins-a"
        self.b.insurer_id = "ins-b"
        self.plans = [self.a1, self.a2, self.b]

    def all_text(self, a):
        return " | ".join(f"{i.kind}:{i.text}" for i in a.items)

    def test_undeclared_condition_never_reported_as_served(self):
        cp = CurrentPolicy(plan_id="a1", sum_insured=10_00_000, continuous_years=4, conditions_declared=False)
        for target in (self.a1, self.b):
            t = self.all_text(analyse(target, cp, self.plans, user(cp)))
            self.assertNotIn("Pre-existing disease", t.split("loss:")[0])
            self.assertIn("did not declare", t)

    def test_migration_with_extra_cover_may_be_underwritten(self):
        cp = CurrentPolicy(plan_id="a1", sum_insured=5_00_000, continuous_years=4)
        t = self.all_text(analyse(self.a2, cp, self.plans, user(cp)))
        self.assertIn("extra Rs 5L may be underwritten", t)
        self.assertNotIn("so no fresh underwriting", t)

    def test_grace_period_for_monthly_payers(self):
        cp = CurrentPolicy(plan_id="a1", sum_insured=10_00_000, continuous_years=4, pays_monthly=True)
        self.assertIn("grace period (15 days)", self.all_text(analyse(self.b, cp, self.plans, user(cp))))

    def test_initial_wait_not_waived_before_12_months_when_porting(self):
        cp = CurrentPolicy(plan_id="a1", sum_insured=10_00_000, continuous_years=0.5)
        self.assertIn("may apply again", self.all_text(analyse(self.b, cp, self.plans, user(cp))))

    def test_unknown_wait_is_flagged_not_dropped(self):
        unknown = plan("u")
        unknown.insurer_id = "ins-u"
        cp = CurrentPolicy(plan_id="a1", sum_insured=10_00_000, continuous_years=4)
        self.assertIn("not known for this plan", self.all_text(analyse(unknown, cp, self.plans + [unknown], user(cp))))

    def test_pregnancy_planner_told_when_candidate_excludes_maternity(self):
        no_mat = plan("nm", maternity_covered=False, maternity_waiting_months=24)
        cp = CurrentPolicy(plan_id="a1", sum_insured=10_00_000, continuous_years=4)
        u = user(cp, members=[Member("You", 30, planning_pregnancy=True)])
        t = self.all_text(analyse(no_mat, cp, self.plans + [no_mat], u))
        self.assertIn("Maternity: not covered by this plan", t)
        self.assertNotIn("Maternity (", t)

    def test_stay_option_when_cover_not_sold(self):
        self.a1.sum_insured_options = [1_50_000, 2_00_000]
        cp = CurrentPolicy(plan_id="a1", sum_insured=2_00_000, continuous_years=4)
        t = self.all_text(analyse(self.a1, cp, self.plans, user(cp)))
        self.assertIn("isn't sold at Rs 10L", t)
        self.assertNotIn("Raise cover", t)

    def test_prices_only_compared_when_both_fit_the_family(self):
        cp = CurrentPolicy(plan_id="a1", sum_insured=10_00_000, continuous_years=4, annual_premium=20000)
        a = analyse(self.b, cp, self.plans, user(cp))
        self.assertFalse(a.comparable_prices)  # no price data for b

    def test_porting_window_edge_cases(self):
        from healthcompare.switching import porting_window
        self.assertIn("passed 10 days ago", porting_window(CurrentPolicy(renewal_in_days=-10)))
        self.assertIn("15-day grace", porting_window(CurrentPolicy(renewal_in_days=-10, pays_monthly=True)))
        self.assertIn("may still be possible", porting_window(CurrentPolicy(renewal_in_days=20)))
        self.assertIn("open now", porting_window(CurrentPolicy(renewal_in_days=45)))
        self.assertIsNone(porting_window(CurrentPolicy(renewal_in_days=45, employer_group=True)))

    def test_group_policy_gets_group_guidance(self):
        cp = CurrentPolicy(name="Employer GMC", sum_insured=5_00_000, continuous_years=3, employer_group=True)
        t = self.all_text(analyse(self.b, cp, self.plans, user(cp)))
        self.assertIn("employer or group policy", t)
        self.assertNotIn("30 to 60 days", t)


class CliInputs(unittest.TestCase):
    def test_numbers_with_commas_and_symbols(self):
        from unittest import mock
        from healthcompare import cli
        with mock.patch("builtins.input", side_effect=["14,000"]):
            self.assertEqual(cli.ask_number("x"), 14000)
        with mock.patch("builtins.input", side_effect=["-1", "abc", "3"]), mock.patch("builtins.print"):
            self.assertEqual(cli.ask_number("x", minimum=0, maximum=5), 3)

    def test_report_lists_current_plan_once_and_unlisted_plan_gets_stay_option(self):
        import io
        from contextlib import redirect_stdout
        from healthcompare import cli
        from healthcompare.engine import rank
        a1 = plan("a1", room_rent_limit="no_limit")
        cp = CurrentPolicy(plan_id="a1", sum_insured=10_00_000, continuous_years=4)
        u = user(cp)
        fit, rej = rank([a1], u, top=None)
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.report(fit, rej, u, top=3, plans=[a1])
        self.assertEqual(buf.getvalue().count("Stay with"), 1)
        other = CurrentPolicy(name="Old plan", sum_insured=5_00_000, continuous_years=2)
        u2 = user(other)
        fit, rej = rank([a1], u2, top=None)
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.report(fit, rej, u2, top=3, plans=[a1])
        self.assertIn("Stay with Your current Old plan", buf.getvalue())

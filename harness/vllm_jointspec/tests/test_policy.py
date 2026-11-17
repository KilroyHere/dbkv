"""Unit tests of the option C allocation policy (pure, no vLLM).

Run: python -m unittest discover -s harness/vllm_jointspec/tests -p 'test_policy.py'
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dbkv_jointspec.policy import AcceptanceTracker, Knobs, _n_at_least, allocate  # noqa: E402


class TestNAtLeast(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_n_at_least(0.5, 10, 0.25), 2)  # 0.5, 0.25
        self.assertEqual(_n_at_least(0.5, 10, 0.26), 1)
        self.assertEqual(_n_at_least(0.5, 1, 0.0), 1)
        self.assertEqual(_n_at_least(0.9, 24, 1.01), 0)
        self.assertEqual(_n_at_least(1.0, 24, 0.5), 24)  # clamped p ~ 1


class TestAllocate(unittest.TestCase):
    def test_no_contention_keeps_everything(self):
        drafts = [("a", 5, 0.8), ("b", 3, 0.3)]
        a = allocate(1000, 10, drafts, prefill_demand=100, theta=0.5)
        self.assertEqual(a.spec, {"a": 5, "b": 3})
        self.assertEqual(a.prefill, 100)
        self.assertLessEqual(a.used, 1000)

    def test_decode_first(self):
        # Budget only covers the decode tokens: no drafts, no prefill.
        a = allocate(10, 10, [("a", 5, 0.99)], prefill_demand=500, theta=0.0)
        self.assertEqual(a.spec, {"a": 0})
        self.assertEqual(a.prefill, 0)
        # Budget smaller than decodes: still nothing else.
        a = allocate(5, 10, [("a", 5, 0.99)], prefill_demand=500)
        self.assertEqual(a.n_spec + a.prefill, 0)

    def test_budget_never_exceeded(self):
        drafts = [(i, 24, 0.1 + 0.85 * (i % 7) / 6) for i in range(80)]
        for B in (100, 300, 900, 2048, 4096):
            for th in (0.0, 0.3, 0.6, 1.5):
                for pf in (0, 200, 5000):
                    a = allocate(B, 80, drafts, pf, theta=th)
                    self.assertLessEqual(a.used, max(B, 80), (B, th, pf))
                    for rid, n, _ in drafts:
                        self.assertLessEqual(a.spec[rid], n)

    def test_theta_split(self):
        # p=0.9: values .9 .81 .729 .656 .59 .53 .48 ... ; 6 positions >= .5
        drafts = [("hi", 24, 0.9), ("lo", 24, 0.3)]  # lo: .3 .09 ...
        a = allocate(2 + 6 + 50, 2, drafts, prefill_demand=1000, theta=0.5)
        self.assertEqual(a.spec["hi"], 6)
        self.assertEqual(a.spec["lo"], 0)
        self.assertEqual(a.prefill, 50)
        self.assertEqual(a.spec_hi, 6)
        self.assertEqual(a.spec_lo, 0)

    def test_theta_zero_is_drafts_first(self):
        drafts = [("a", 10, 0.6), ("b", 10, 0.6)]
        a = allocate(2 + 20 + 5, 2, drafts, prefill_demand=100, theta=0.0)
        self.assertEqual(a.n_spec, 20)
        self.assertEqual(a.prefill, 5)

    def test_theta_above_one_is_prefill_first(self):
        drafts = [("a", 10, 0.99)]
        a = allocate(1 + 30, 1, drafts, prefill_demand=25, theta=2.0)
        self.assertEqual(a.prefill, 25)
        self.assertEqual(a.spec["a"], 5)  # leftover fill
        a = allocate(1 + 30, 1, drafts, prefill_demand=25, theta=2.0, fill_leftover=False)
        self.assertEqual(a.spec["a"], 0)

    def test_leftover_fill_and_min_value(self):
        drafts = [("a", 10, 0.5)]  # .5 .25 .125 .0625 ...
        a = allocate(1 + 100, 1, drafts, prefill_demand=0, theta=0.4, min_value=0.1)
        self.assertEqual(a.spec["a"], 3)  # .5 (hi), .25 .125 (lo); .0625 < min
        self.assertEqual((a.spec_hi, a.spec_lo), (1, 2))

    def test_proportional_to_acceptance(self):
        # Contended: more drafts go to the higher-acceptance request.
        drafts = [("good", 24, 0.85), ("bad", 24, 0.4)]
        a = allocate(2 + 12, 2, drafts, prefill_demand=0, theta=0.0)
        self.assertEqual(a.n_spec, 12)
        self.assertGreater(a.spec["good"], a.spec["bad"])
        # Greedy optimality: the k-th draft of "bad" is never taken while a
        # strictly better position of "good" is left out.
        kg, kb = a.spec["good"], a.spec["bad"]
        if kb > 0 and kg < 24:
            self.assertLessEqual(0.85 ** (kg + 1), 0.4 ** kb + 1e-12)

    def test_speed(self):
        drafts = [(i, 24, 0.3 + 0.6 * (i % 11) / 10) for i in range(128)]
        t = time.perf_counter()
        for _ in range(50):
            allocate(1024, 128, drafts, prefill_demand=3000, theta=0.5)
        ms = (time.perf_counter() - t) / 50 * 1e3
        print(f"\nallocate(): 128 reqs x 24 drafts: {ms:.2f} ms/step")
        self.assertLess(ms, 20.0)


class TestTracker(unittest.TestCase):
    def test_converges(self):
        # Long EWMA window so the test checks the estimator, not its noise.
        tr = AcceptanceTracker(ewma=0.998, prior_weight=4.0, p_init=0.6)
        # Process with p=0.8: draft 10, accept geometric -> feed expected-ish.
        import random

        rng = random.Random(0)
        for _ in range(2000):
            m = 0
            while m < 10 and rng.random() < 0.8:
                m += 1
            tr.observe("r", 10, m)
        self.assertAlmostEqual(tr.p("r"), 0.8, delta=0.05)
        self.assertAlmostEqual(tr.global_p(), 0.8, delta=0.05)

    def test_prior_shrinkage(self):
        tr = AcceptanceTracker(ewma=1.0, prior_weight=4.0, p_init=0.6)
        self.assertAlmostEqual(tr.p("new"), 0.6)
        tr.observe("x", 5, 0)  # one rejection at position 1
        self.assertLess(tr.p("x"), tr.global_p())
        self.assertGreater(tr.p("x"), 0.0)
        tr.observe("y", 5, 5)  # all accepted: 5 successes, no failure
        self.assertGreater(tr.p("y"), tr.p("x"))
        tr.forget(["y"])
        self.assertNotIn("x", tr.per_req)

    def test_knobs_env(self):
        k = Knobs.from_env({"DBKV_JOINTSPEC": "1", "DBKV_JOINTSPEC_BUDGET": "768",
                            "DBKV_JOINTSPEC_THETA": "0.3", "DBKV_JOINTSPEC_FILL_LEFTOVER": "0"})
        self.assertTrue(k.enabled)
        self.assertEqual(k.budget, 768)
        self.assertEqual(k.theta, 0.3)
        self.assertFalse(k.fill_leftover)
        self.assertFalse(Knobs.from_env({}).enabled)


if __name__ == "__main__":
    unittest.main()

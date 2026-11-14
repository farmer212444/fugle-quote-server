"""Regression: post-close issuer earnings must not be priced at a prior close."""
import unittest

from tw_model_v880.data import quarantine_post_price_close_events


class IssuerEarningsPriceCutoffTests(unittest.TestCase):
    def test_same_day_before_close_accepted(self):
        events = {"2382": {"available_at": "2026-11-13T13:29:59+08:00"}}
        admitted, state = quarantine_post_price_close_events(events, {}, "2026-11-13")
        self.assertEqual(admitted, events)
        self.assertEqual(state, {})

    def test_same_day_after_close_is_blocked(self):
        events = {"2317": {"available_at": "2026-11-12T14:15:06+08:00"}}
        admitted, states = quarantine_post_price_close_events(events, {}, "2026-11-12")
        self.assertNotIn("2317", admitted)
        self.assertTrue(states["2317"]["blocks_current_decision"])
        self.assertEqual(states["2317"]["status"], "EARNINGS_CAPTURE_AFTER_REFERENCE_CLOSE")
        self.assertFalse(states["2317"]["issuer_first_publication_PIT_verified"])

    def test_earlier_day_post_close_ok_for_next_session(self):
        events = {"2382": {"available_at": "2026-11-11T15:01:00+08:00"}}
        admitted, states = quarantine_post_price_close_events(events, {}, "2026-11-12")
        self.assertIn("2382", admitted)
        self.assertEqual(states, {})

    def test_mixed_issuers_quarantine_only_late_and_keep_existing_flags(self):
        events = {
            "2382": {"available_at": "2026-11-11T15:01:00+08:00"},
            "2317": {"available_at": "2026-11-12T14:15:06+08:00"},
            "2404": {"available_at": "2026-11-12T17:33:03+08:00"},
        }
        original_states = {"2382": {"status": "RESEARCH_ONLY", "blocks_current_decision": False}}
        admitted, states = quarantine_post_price_close_events(events, original_states, "2026-11-12")
        self.assertEqual(set(admitted), {"2382"})
        self.assertEqual(states["2382"], original_states["2382"])
        for code in ("2317", "2404"):
            self.assertTrue(states[code]["blocks_current_decision"])

    def test_missing_naive_and_bad_timestamps_fail_closed(self):
        for bad in (None, "2026-11-12T10:00:00", "not-a-timestamp"):
            with self.subTest(bad=bad):
                admitted, states = quarantine_post_price_close_events(
                    {"2317": {"available_at": bad}}, {}, "2026-11-12")
                self.assertEqual(admitted, {})
                self.assertEqual(states["2317"]["status"], "EARNINGS_CAPTURE_TIME_MISSING_OR_INVALID")
                self.assertTrue(states["2317"]["blocks_current_decision"])

    def test_utc_offset_is_respected_and_inputs_not_mutated(self):
        events = {"2317": {"available_at": "2026-11-12T05:29:59Z"}}
        states = {}
        admitted, decisions = quarantine_post_price_close_events(events, states, "2026-11-12")
        self.assertEqual(admitted, events)
        self.assertEqual(decisions, {})
        self.assertEqual(states, {})
        self.assertEqual(events["2317"]["available_at"], "2026-11-12T05:29:59Z")


if __name__ == "__main__":
    unittest.main()

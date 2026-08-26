"""
Unit & Integration Tests for Coach Engine
==========================================
Tests state management, staleness rules, zone generation, workout analysis,
aerobic decoupling, and plan generation.
"""

import os
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from coach_engine.tools.state_manager import StateManager
from coach_engine.tools.workout_analyzer import (
    compute_aerobic_decoupling,
    analyze_lap_splits,
    analyze_interval_compliance,
    detect_fatigue_and_recovery_status,
    generate_workout_review_report,
    sec_to_pace_str,
    speed_to_pace_sec,
)
from coach_engine.tools.plan_generator import WorkoutPlanGenerator
from coach_engine.tools.intervals_api import IntervalsAPIClient, IntervalsAPIError


class TestStateManager(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.profile_path = Path(self.temp_dir.name) / "athlete_profile.json"
        self.rules_path = Path(self.temp_dir.name) / "staleness_rules.json"

        # Write default staleness rules
        rules = {
            "weight_kg": 14,
            "resting_hr_baseline": 30,
            "lthr_bpm": 60,
            "threshold_pace_sec_km": 45,
            "max_hr_bpm": 90,
            "target_events": 30,
            "weekly_availability": 30,
        }
        with open(self.rules_path, "w", encoding="utf-8") as f:
            json.dump(rules, f)

        self.sm = StateManager(profile_path=self.profile_path, staleness_rules_path=self.rules_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_uninitialized_state(self):
        self.assertFalse(self.sm.is_initialized())
        stale = self.sm.get_stale_metrics()
        self.assertEqual(stale, [])

    def test_initialization_and_zones(self):
        onboarding_data = {
            "name": "Eliud Runner",
            "birth_date": "1990-05-15",
            "weight_kg": 65.0,
            "resting_hr_baseline": 45,
            "max_hr_bpm": 190,
            "lthr_bpm": 172,
            "threshold_pace_sec_km": 240.0,  # 4:00/km
            "coaching_philosophy": "Polarized 80/20",
            "target_events": [
                {
                    "name": "Valencia Marathon",
                    "date": "2026-12-06",
                    "distance_km": 42.195,
                    "goal_time_sec": 10200,
                    "priority": "A",
                }
            ],
            "weekly_availability": {
                "monday": "Rest",
                "tuesday": "Intervals",
                "wednesday": "Easy 10k",
                "thursday": "Tempo",
                "friday": "Rest",
                "saturday": "Long Run",
                "sunday": "Recovery",
            },
        }

        profile = self.sm.initialize_profile(onboarding_data)
        self.assertTrue(self.sm.is_initialized())
        self.assertEqual(profile["personal"]["name"], "Eliud Runner")
        self.assertEqual(profile["personal"]["weight_kg"]["value"], 65.0)
        self.assertEqual(len(profile["metrics"]["hr_zones"]), 5)
        self.assertEqual(len(profile["metrics"]["pace_zones"]), 6)

        # Verify HR zones
        z2 = profile["metrics"]["hr_zones"][1]
        self.assertEqual(z2["zone"], "Z2")
        # 172 * 0.80 = 138 (Z1 max) -> Z2 min = 139, Z2 max = 172 * 0.89 = 153
        self.assertEqual(z2["min"], 139)
        self.assertEqual(z2["max"], 153)

        # Fresh profile should have no stale metrics
        stale = self.sm.get_stale_metrics()
        self.assertEqual(len(stale), 0)

    def test_staleness_detection(self):
        # Initialize profile with an old timestamp for weight
        self.test_initialization_and_zones()
        
        # Simulate 20 days in the future for staleness check
        future_time = datetime.now(timezone.utc) + timedelta(days=20)
        stale = self.sm.get_stale_metrics(current_time=future_time)
        
        # weight_kg TTL is 14 days, so it should be stale after 20 days
        stale_fields = [s["field"] for s in stale]
        self.assertIn("weight_kg", stale_fields)

        # Update weight to now
        self.sm.update_profile({"weight_kg": 64.5})
        profile = self.sm.get_profile()
        self.assertEqual(profile["personal"]["weight_kg"]["value"], 64.5)


class TestWorkoutAnalyzer(unittest.TestCase):

    def test_pace_conversions(self):
        # 4:00/km is 240 seconds/km
        self.assertEqual(sec_to_pace_str(240), "4:00/km")
        self.assertEqual(sec_to_pace_str(285), "4:45/km")
        # 4.167 m/s is 240 sec/km
        self.assertAlmostEqual(speed_to_pace_sec(4.16667), 240.0, places=1)

    def test_aerobic_decoupling_with_streams(self):
        # 600 seconds with steady speed and minimal HR drift (Decoupling ~ 0%)
        time_points = 600
        hr_stream = [140] * 300 + [141] * 300
        speed_stream = [3.5] * 600  # 3.5 m/s

        streams = {
            "heartrate": hr_stream,
            "velocity_smooth": speed_stream,
        }
        activity = {"type": "Run", "name": "Steady Base Run"}
        result = compute_aerobic_decoupling(activity, streams=streams)
        
        self.assertIn("decoupling_pct", result)
        self.assertLess(result["decoupling_pct"], 3.5)
        self.assertEqual(result["classification"], "EXCELLENT")

    def test_aerobic_decoupling_excessive(self):
        # Heart rate drifts significantly in second half (140 -> 165 bpm at same speed)
        hr_stream = [140] * 300 + [165] * 300
        speed_stream = [3.5] * 600

        streams = {
            "heartrate": hr_stream,
            "velocity_smooth": speed_stream,
        }
        activity = {"type": "Run", "name": "Fatiguing Long Run"}
        result = compute_aerobic_decoupling(activity, streams=streams)
        
        self.assertGreater(result["decoupling_pct"], 7.5)
        self.assertEqual(result["classification"], "EXCELLENT" if result["decoupling_pct"] < 3.5 else "EXCESSIVE_DECOUPLING")

    def test_interval_compliance_and_fade(self):
        activity = {
            "type": "Run",
            "icu_intervals": [
                {"id": 1, "type": "WORK", "distance": 1000, "moving_time": 210, "average_heartrate": 168},  # 3:30/km
                {"id": 2, "type": "RECOVERY", "distance": 400, "moving_time": 120, "average_heartrate": 130},
                {"id": 3, "type": "WORK", "distance": 1000, "moving_time": 212, "average_heartrate": 170},  # 3:32/km
                {"id": 4, "type": "RECOVERY", "distance": 400, "moving_time": 120, "average_heartrate": 132},
                {"id": 5, "type": "WORK", "distance": 1000, "moving_time": 211, "average_heartrate": 172},  # 3:31/km
            ]
        }
        compliance = analyze_interval_compliance(activity)
        self.assertEqual(compliance["work_intervals_count"], 3)
        self.assertEqual(compliance["compliance_verdict"], "PERFECT_EXECUTION")

    def test_fatigue_and_recovery_detection(self):
        # Normal wellness records
        wellness_data = [
            {"id": "2026-08-20", "hrv": 65, "restingHR": 48, "sleepSecs": 28800, "sleepScore": 85, "ctl": 60, "atl": 65},
            {"id": "2026-08-21", "hrv": 68, "restingHR": 47, "sleepSecs": 29000, "sleepScore": 88, "ctl": 60, "atl": 64},
            {"id": "2026-08-22", "hrv": 66, "restingHR": 48, "sleepSecs": 28000, "sleepScore": 82, "ctl": 60, "atl": 63},
            {"id": "2026-08-23", "hrv": 67, "restingHR": 47, "sleepSecs": 30000, "sleepScore": 90, "ctl": 60, "atl": 62},
        ]
        status_green = detect_fatigue_and_recovery_status(wellness_data)
        self.assertEqual(status_green["status"], "GREEN")

        # Suppressed HRV & elevated RHR (Red status)
        wellness_data_red = wellness_data + [
            {"id": "2026-08-24", "hrv": 42, "restingHR": 55, "sleepSecs": 18000, "sleepScore": 45, "fatigue": 8, "soreness": 8, "ctl": 60, "atl": 92}
        ]
        status_red = detect_fatigue_and_recovery_status(wellness_data_red)
        self.assertEqual(status_red["status"], "RED")
        self.assertIn("SUPPRESSED", status_red["hrv_status"])


class TestPlanGenerator(unittest.TestCase):

    def test_plan_templates(self):
        easy_run = WorkoutPlanGenerator.create_easy_aerobic_run(duration_min=50)
        self.assertIn("50m", easy_run["name"])
        self.assertIn("68% HR", easy_run["description"])

        vo2_workout = WorkoutPlanGenerator.create_vo2max_intervals(reps=5, rep_spec="1000m")
        self.assertEqual(vo2_workout["name"], "5x1000m VO2max Intervals")
        self.assertIn("5x\n- 1000m 95-100% PACE", vo2_workout["description"])

        cycling_ss = WorkoutPlanGenerator.create_sweet_spot_cycling(reps=3, rep_duration_min=15)
        self.assertEqual(cycling_ss["type"], "Ride")
        self.assertIn("88-94% FTP", cycling_ss["description"])

    def test_dynamic_adaptation(self):
        planned = WorkoutPlanGenerator.create_vo2max_intervals(reps=5)
        planned["start_date_local"] = "2026-08-27T07:00:00"
        planned["id"] = 999

        # RED readiness adaptation
        adapted_red = WorkoutPlanGenerator.adapt_workout_for_readiness(planned, "RED")
        self.assertTrue(adapted_red["adapted"])
        self.assertEqual(adapted_red["action"], "DOWNGRADED_TO_RECOVERY")
        self.assertIn("Active Recovery", adapted_red["workout"]["name"])

        # AMBER readiness adaptation
        adapted_amber = WorkoutPlanGenerator.adapt_workout_for_readiness(planned, "AMBER")
        self.assertTrue(adapted_amber["adapted"])
        self.assertEqual(adapted_amber["action"], "VOLUME_OR_INTENSITY_REDUCED")


class TestIntervalsAPIClient(unittest.TestCase):

    def test_auth_and_caching(self):
        client = IntervalsAPIClient(api_key="test_key_123", athlete_id="i999")
        self.assertTrue(client.is_authenticated)
        self.assertEqual(client.auth.username, "API_KEY")
        self.assertEqual(client.auth.password, "test_key_123")

        # Test offline cache write/read
        test_payload = {"status": "ok", "items": [1, 2, 3]}
        client._write_cache("test_key", test_payload)
        cached = client._read_cache("test_key")
        self.assertEqual(cached, test_payload)


if __name__ == "__main__":
    unittest.main()

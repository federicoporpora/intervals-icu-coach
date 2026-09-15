"""
Unit Tests for Dual-Horizon Memory Manager
==========================================
Tests long-term memory CRUD, short-term calendar constraints, Intervals.icu sync,
follow-up reminders lifecycle, temporary physiological statuses, pruning, and prompt formatting.
"""

import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock

from coach_engine.tools.memory_manager import MemoryManager, get_memory_manager
from coach_engine.tools.plan_generator import WorkoutPlanGenerator
from coach_engine.tools.intervals_api import IntervalsAPIClient


class TestMemoryManager(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.memory_path = Path(self.temp_dir.name) / "athlete_memory.json"
        self.mm = MemoryManager(memory_path=self.memory_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_default_memory_structure(self):
        mem = self.mm.get_memory()
        self.assertEqual(mem["version"], "1.0")
        self.assertIn("long_term", mem)
        self.assertIn("short_term", mem)
        self.assertIn("physiological_traits", mem["long_term"])
        self.assertIn("calendar_constraints", mem["short_term"])
        self.assertIn("follow_ups_and_reminders", mem["short_term"])

    def test_long_term_memory_crud(self):
        # 1. Add item
        item1 = self.mm.add_long_term_memory(
            content="Prone to patellar tendon flare-ups over 60km/week",
            category="physiological_traits",
            tags=["knee", "volume", "injury"],
        )
        self.assertTrue(item1["id"].startswith("lt_"))
        self.assertEqual(item1["category"], "physiological_traits")
        self.assertIn("knee", item1["tags"])

        item2 = self.mm.add_long_term_memory(
            content="Prefers long runs on Saturday morning",
            category="preferences_and_habits",
            tags=["schedule", "long_run"],
        )

        # 2. Get by category and tag
        traits = self.mm.get_long_term_memories(category="physiological_traits")
        self.assertEqual(len(traits), 1)
        self.assertEqual(traits[0]["id"], item1["id"])

        knee_tagged = self.mm.get_long_term_memories(tag="knee")
        self.assertEqual(len(knee_tagged), 1)
        self.assertEqual(knee_tagged[0]["id"], item1["id"])

        all_items = self.mm.get_long_term_memories()
        self.assertEqual(len(all_items), 2)

        # 3. Update item
        updated = self.mm.update_long_term_memory(
            memory_id=item1["id"],
            content="Prone to patellar tendon flare-ups over 55km/week",
            tags=["knee", "volume", "patella"],
        )
        self.assertIsNotNone(updated)
        self.assertIn("55km", updated["content"])
        self.assertIn("patella", updated["tags"])

        # 4. Delete item
        deleted = self.mm.delete_long_term_memory(item2["id"])
        self.assertTrue(deleted)
        self.assertEqual(len(self.mm.get_long_term_memories()), 1)

    def test_calendar_constraints_and_blocking(self):
        today = datetime.now(timezone.utc).date()
        d_exam = (today + timedelta(days=2)).isoformat()
        d_free = (today + timedelta(days=3)).isoformat()
        d_vac_start = (today + timedelta(days=10)).isoformat()
        d_vac_end = (today + timedelta(days=14)).isoformat()
        d_vac_during = (today + timedelta(days=11)).isoformat()
        d_before = (today + timedelta(days=1)).isoformat()

        # Add constraint: University exam
        c1 = self.mm.add_calendar_constraint(
            date_start=d_exam,
            date_end=d_exam,
            description="University Exam - no training",
            constraint_type="exam",
            action="no_training",
        )
        self.assertTrue(c1["id"].startswith("st_c_"))
        self.assertEqual(c1["date_start"], d_exam)
        self.assertEqual(c1["date_end"], d_exam)

        # Add multi-day constraint: Vacation
        c2 = self.mm.add_calendar_constraint(
            date_start=d_vac_start,
            date_end=d_vac_end,
            description="Family Vacation - easy runs only",
            constraint_type="holiday",
            action="easy_only",
        )

        # Check date blocking
        blocked, constraint = self.mm.is_date_blocked(d_exam)
        self.assertTrue(blocked)
        self.assertEqual(constraint["description"], "University Exam - no training")

        blocked_free, _ = self.mm.is_date_blocked(d_free)
        self.assertFalse(blocked_free)

        # Easy only constraint should not be strictly blocked for 'no_training'
        blocked_vacation, _ = self.mm.is_date_blocked(d_vac_during)
        self.assertFalse(blocked_vacation)

        # Query range
        active = self.mm.get_active_calendar_constraints(start_date=d_exam, end_date=(today + timedelta(days=5)).isoformat())
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["id"], c1["id"])

        # Test filtering available training days in plan generator
        days = [d_before, d_exam, d_free]
        avail = WorkoutPlanGenerator.filter_available_training_days(days, self.mm)
        self.assertEqual(avail, [d_before, d_free])

        # Remove constraint
        removed = self.mm.remove_calendar_constraint(c1["id"])
        self.assertTrue(removed)
        blocked_after, _ = self.mm.is_date_blocked(d_exam)
        self.assertFalse(blocked_after)

    def test_intervals_calendar_sync(self):
        mock_client = MagicMock()
        mock_client.create_calendar_holiday.return_value = {"id": 987654, "status": "created"}
        mock_client.delete_calendar_event.return_value = {"status": "deleted"}

        # Add constraint with sync
        c = self.mm.add_calendar_constraint(
            date_start="2026-09-01",
            description="University Exam",
            constraint_type="exam",
            action="no_training",
            sync_intervals=True,
            intervals_client=mock_client,
        )
        self.assertTrue(c["synced_to_intervals"])
        self.assertEqual(c["intervals_event_id"], "987654")
        mock_client.create_calendar_holiday.assert_called_once()

        # Remove constraint with sync deletion
        self.mm.remove_calendar_constraint(
            c["id"],
            delete_from_intervals=True,
            intervals_client=mock_client,
        )
        mock_client.delete_calendar_event.assert_called_once_with("987654")

    def test_follow_up_reminders_lifecycle(self):
        # 1. Add reminders
        r1 = self.mm.add_follow_up_reminder(
            description="Ask athlete for RPE and subjective feeling of 5x1k VO2max",
            trigger_condition="next_interaction",
            priority="high",
        )
        r2 = self.mm.add_follow_up_reminder(
            description="Check knee sensation after tomorrow's easy 10k",
            trigger_condition="next_interaction",
            priority="normal",
        )

        # 2. Get pending (high priority first)
        pending = self.mm.get_pending_follow_ups()
        self.assertEqual(len(pending), 2)
        self.assertEqual(pending[0]["id"], r1["id"])
        self.assertEqual(pending[0]["priority"], "high")

        # 3. Complete reminder
        completed = self.mm.complete_follow_up(r1["id"], completion_notes="Athlete reported RPE 8/10, felt strong")
        self.assertTrue(completed)

        # 4. Check pending again
        pending_after = self.mm.get_pending_follow_ups()
        self.assertEqual(len(pending_after), 1)
        self.assertEqual(pending_after[0]["id"], r2["id"])

        # 5. Dismiss reminder
        dismissed = self.mm.dismiss_follow_up(r2["id"])
        self.assertTrue(dismissed)
        self.assertEqual(len(self.mm.get_pending_follow_ups()), 0)

    def test_temporary_physiological_status(self):
        s1 = self.mm.add_temporary_status(
            description="Mild left calf tightness",
            severity="mild",
            duration_days=3,
            date_recorded="2026-08-30",
        )
        self.assertTrue(s1["id"].startswith("st_p_"))
        self.assertEqual(s1["severity"], "mild")
        self.assertEqual(s1["expires_at"], "2026-09-02T23:59:59Z")

        active = self.mm.get_active_temporary_statuses(as_of_date="2026-08-31")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["description"], "Mild left calf tightness")

        # Expired check
        active_expired = self.mm.get_active_temporary_statuses(as_of_date="2026-09-05")
        self.assertEqual(len(active_expired), 0)

    def test_pruning_expired_entries(self):
        # Add constraint expiring 2026-09-01
        self.mm.add_calendar_constraint(
            date_start="2026-09-01",
            date_end="2026-09-01",
            description="Exam",
        )
        # Add temporary status expiring 2026-09-02
        self.mm.add_temporary_status(
            description="Mild soreness",
            duration_days=2,
            date_recorded="2026-08-31",
        )

        # Prune as of 2026-09-05 (both expired)
        res = self.mm.prune_expired_entries(as_of_date="2026-09-05")
        self.assertEqual(res["pruned_constraints"], 1)
        self.assertEqual(res["pruned_statuses"], 1)

        mem = self.mm.get_memory()
        self.assertEqual(len(mem["short_term"]["calendar_constraints"]), 0)
        self.assertEqual(len(mem["short_term"]["temporary_physiological_status"]), 0)

    def test_prompt_summary_formatting(self):
        self.mm.add_long_term_memory(
            content="Heart-rate-first paradigm (<154 bpm in Z2)",
            category="coaching_directives",
            tags=["hr", "zone2"],
        )
        self.mm.add_calendar_constraint(
            date_start="2026-09-01",
            date_end="2026-09-01",
            description="University Exam",
            action="no_training",
        )
        self.mm.add_follow_up_reminder(
            description="Ask athlete for RPE on 5x1k",
            priority="high",
        )
        self.mm.add_temporary_status(
            description="Mild calf tightness",
            severity="mild",
            date_recorded="2026-08-30",
        )

        prompt_str = self.mm.format_memory_summary_for_prompt(as_of_date="2026-08-30")
        self.assertIn("Coach Active Memory Context", prompt_str)
        self.assertIn("PENDING FOLLOW-UPS & REMINDERS", prompt_str)
        self.assertIn("Ask athlete for RPE on 5x1k", prompt_str)
        self.assertIn("ACTIVE SHORT-TERM CALENDAR CONSTRAINTS", prompt_str)
        self.assertIn("University Exam", prompt_str)
        self.assertIn("TEMPORARY PHYSIOLOGICAL STATUS", prompt_str)
        self.assertIn("Mild calf tightness", prompt_str)
        self.assertIn("LONG-TERM ATHLETE TRAITS & DIRECTIVES", prompt_str)
        self.assertIn("Heart-rate-first paradigm", prompt_str)

    def test_sync_calendar_constraints_from_intervals(self):
        class MockIntervalsClient:
            def get_events(self, oldest, newest):
                return [
                    {
                        "id": 101,
                        "category": "NOTE",
                        "name": "CONTROLLI AUTOMATICI",
                        "start_date_local": "2026-09-10T00:00:00",
                        "end_date_local": "2026-09-11T00:00:00",
                        "description": "",
                    },
                    {
                        "id": 102,
                        "category": "NOTE",
                        "name": "investimenti",
                        "start_date_local": "2026-09-14T00:00:00",
                        "end_date_local": "2026-09-15T00:00:00",
                        "description": "",
                    },
                    {
                        "id": 103,
                        "category": "NOTE",
                        "name": "USCITA DI COCA",
                        "start_date_local": "2026-09-26T00:00:00",
                        "end_date_local": "2026-09-28T00:00:00",
                        "description": "",
                    },
                    {
                        "id": 104,
                        "category": "WORKOUT",
                        "name": "5x1k Intervals",
                        "start_date_local": "2026-09-15T06:30:00",
                    },
                    {
                        "id": 105,
                        "category": "RACE_A",
                        "name": "Maratonina",
                        "start_date_local": "2026-10-25T09:00:00",
                    }
                ]

        mock_client = MockIntervalsClient()
        imported = self.mm.sync_calendar_constraints_from_intervals(mock_client, "2026-09-08", "2026-10-31")
        self.assertEqual(len(imported), 3)

        # 101 should be blocked (exam)
        c101 = next(c for c in imported if c["intervals_event_id"] == "101")
        self.assertEqual(c101["action"], "no_training")
        self.assertEqual(c101["date_start"], "2026-09-10")
        self.assertEqual(c101["date_end"], "2026-09-10")

        # 102 should be available (reminder)
        c102 = next(c for c in imported if c["intervals_event_id"] == "102")
        self.assertEqual(c102["action"], "available")

        # 103 should be multi-day blocked (scout outing)
        c103 = next(c for c in imported if c["intervals_event_id"] == "103")
        self.assertEqual(c103["action"], "no_training")
        self.assertEqual(c103["date_start"], "2026-09-26")
        self.assertEqual(c103["date_end"], "2026-09-27")


if __name__ == "__main__":
    unittest.main()


"""
Unit Tests for External Calendar Synchronizer
=============================================
Tests iCal parsing, timezone handling, commute and recovery buffer solving,
daily schedule analysis, and MemoryManager integration.
"""

import tempfile
import unittest
from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from unittest.mock import patch, MagicMock

from coach_engine.tools.external_calendar import ExternalCalendarManager
from coach_engine.tools.memory_manager import MemoryManager


class TestExternalCalendarManager(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self.temp_dir.name) / "cache"
        self.config_path = Path(self.temp_dir.name) / "athlete_profile.json"
        self.memory_path = Path(self.temp_dir.name) / "athlete_memory.json"

        # Write dummy athlete profile
        config_data = {
            "preferences": {
                "integrations": {
                    "external_calendars": [
                        {
                            "name": "Test Personal",
                            "url": "https://example.com/personal.ics",
                            "type": "personal",
                            "commute_minutes": 0,
                            "enabled": True,
                        },
                        {
                            "name": "Test University",
                            "url": "webcal://example.com/uni.ics",
                            "type": "university",
                            "commute_minutes": 45,
                            "enabled": True,
                        },
                    ]
                }
            }
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            import json
            json.dump(config_data, f)

        self.ecm = ExternalCalendarManager(
            config_path=self.config_path,
            cache_dir=self.cache_dir,
            timezone_name="Europe/Rome",
        )
        self.mm = MemoryManager(memory_path=self.memory_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_get_calendar_sources(self):
        sources = self.ecm.get_calendar_sources()
        self.assertEqual(len(sources), 2)
        self.assertEqual(sources[0]["name"], "Test Personal")
        self.assertEqual(sources[1]["type"], "university")

    def test_parse_datetime(self):
        # 1. UTC Z timestamp
        dt_utc, all_day = self.ecm.parse_datetime("20260916T100000Z")
        self.assertFalse(all_day)
        # Rome is UTC+2 in September (CEST) -> 12:00
        self.assertEqual(dt_utc.hour, 12)
        self.assertEqual(dt_utc.minute, 0)

        # 2. All-day date
        dt_day, is_all_day = self.ecm.parse_datetime("20260916")
        self.assertTrue(is_all_day)
        self.assertEqual(dt_day.date(), date(2026, 9, 16))

    def test_parse_ical_unfolding_and_escapes(self):
        sample_ical = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:evt-1
SUMMARY:ARCHITETTURE DEI
  CALCOLATORI M
LOCATION:AULA 5.7\\, Viale del Risorgimento\\, 2 - Bologna
DTSTART:20260916T100000Z
DTEND:20260916T123000Z
END:VEVENT
BEGIN:VEVENT
UID:evt-2
SUMMARY:ESAME CONTROLLI AUTOMATICI
DTSTART:20260918
DTEND:20260919
END:VEVENT
END:VCALENDAR"""

        events = self.ecm.parse_ical(
            sample_ical,
            cal_name="UniBo",
            cal_type="university",
            default_commute_minutes=45,
        )

        self.assertEqual(len(events), 2)
        # Event 1
        ev1 = events[0]
        self.assertEqual(ev1["summary"], "ARCHITETTURE DEI CALCOLATORI M")
        self.assertEqual(ev1["location"], "AULA 5.7, Viale del Risorgimento, 2 - Bologna")
        self.assertEqual(ev1["category"], "lecture")
        self.assertEqual(ev1["commute_minutes"], 45)
        self.assertEqual(ev1["start_dt"].hour, 12)
        self.assertEqual(ev1["end_dt"].hour, 14)
        self.assertEqual(ev1["end_dt"].minute, 30)

        # Event 2
        ev2 = events[1]
        self.assertEqual(ev2["summary"], "ESAME CONTROLLI AUTOMATICI")
        self.assertEqual(ev2["category"], "exam")
        self.assertTrue(ev2["all_day"])

    def test_daily_schedule_and_commute_buffers(self):
        sample_ical = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:evt-1
SUMMARY:Lezione Sistemi
DTSTART:20260916T100000Z
DTEND:20260916T123000Z
END:VEVENT
BEGIN:VEVENT
UID:evt-2
SUMMARY:Lezione Architetture
DTSTART:20260916T130000Z
DTEND:20260916T160000Z
END:VEVENT
END:VCALENDAR"""

        events = self.ecm.parse_ical(
            sample_ical,
            cal_name="UniBo",
            cal_type="university",
            default_commute_minutes=45,
        )

        with patch.object(self.ecm, "get_events", return_value=events):
            sched = self.ecm.get_daily_schedule("2026-09-16")
            self.assertEqual(sched["events_count"], 2)

            # Check busy blocks: 12:00-14:30 with 45m commute -> 11:15-15:15
            # and 15:00-18:00 with 45m commute -> 14:15-18:45
            # Merged busy window is 11:15 - 18:45
            free = sched["free_windows"]
            self.assertTrue(len(free) >= 2)
            # Morning window from 06:00 to 11:15 (start of commute)
            self.assertEqual(free[0]["start"], "06:00")
            self.assertEqual(free[0]["end"], "11:15")
            # Evening window from 18:45 (end of return commute) to 22:00
            self.assertEqual(free[1]["start"], "18:45")
            self.assertEqual(free[1]["end"], "22:00")

    def test_optimal_training_slot_solver(self):
        sample_ical = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:evt-1
SUMMARY:Lezione Mattina
DTSTART:20260916T070000Z
DTEND:20260916T090000Z
END:VEVENT
END:VCALENDAR"""

        events = self.ecm.parse_ical(
            sample_ical,
            cal_name="UniBo",
            cal_type="university",
            default_commute_minutes=45,
        )

        with patch.object(self.ecm, "get_events", return_value=events):
            # Event is 09:00 - 11:00 local time. Commute: 08:15 to 11:45
            # Morning free: 06:00 - 08:15 (135 min)
            slot = self.ecm.find_optimal_training_slot(
                target_date="2026-09-16",
                workout_duration_min=45,
                shower_buffer_min=35,
                preference="morning",
            )
            self.assertIsNotNone(slot)
            self.assertEqual(slot["recommended_start"], "06:00")
            self.assertEqual(slot["recommended_end"], "06:45")
            self.assertEqual(slot["post_workout_ready"], "07:20")
            # Ready at 07:20 is well before 08:15 commute departure!
            self.assertTrue(slot["margin_minutes"] >= 50)

    def test_sync_to_memory_manager(self):
        sample_ical = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:evt-1
SUMMARY:ARCHITETTURE DEI CALCOLATORI M
DTSTART:20260916T100000Z
DTEND:20260916T123000Z
END:VEVENT
END:VCALENDAR"""

        events = self.ecm.parse_ical(sample_ical, cal_name="UniBo", cal_type="university")
        with patch.object(self.ecm, "get_events", return_value=events):
            imported = self.ecm.sync_to_memory_manager(self.mm, days_ahead=7)
            self.assertEqual(len(imported), 1)
            self.assertEqual(imported[0]["type"], "lecture")
            self.assertEqual(imported[0]["action"], "busy_window")

            # Check memory manager stored it
            constraints = self.mm.get_active_calendar_constraints(for_date="2026-09-16")
            self.assertEqual(len(constraints), 1)
            self.assertIn("ARCHITETTURE", constraints[0]["description"])


if __name__ == "__main__":
    unittest.main()

"""
External Calendar & Schedule Synchronizer
=========================================
Parses external iCal / webcal feeds (Google Calendar, university feeds like UniBo),
calculates daily busy blocks, commute buffers, post-workout recovery buffers,
and provides deterministic availability windows for workout scheduling.
"""

import os
import re
import json
import hashlib
from datetime import datetime, timezone, date, time as dt_time, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union
from zoneinfo import ZoneInfo
import requests


class ExternalCalendarManager:
    """Manages ingestion and schedule calculation from external iCal feeds."""

    DEFAULT_TIMEZONE = "Europe/Rome"

    def __init__(
        self,
        config_path: Optional[Union[str, Path]] = None,
        cache_dir: Optional[Union[str, Path]] = None,
        timezone_name: str = DEFAULT_TIMEZONE,
    ):
        base_dir = Path(__file__).resolve().parent.parent
        self.config_path = Path(config_path) if config_path else base_dir / "config" / "athlete_profile.json"
        self.cache_dir = Path(cache_dir) if cache_dir else base_dir / "data" / "cache" / "calendars"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.tz = ZoneInfo(timezone_name)

    # --------------------------------------------------------------------------
    # 1. Calendar Configuration
    # --------------------------------------------------------------------------
    def get_calendar_sources(self) -> List[Dict[str, Any]]:
        """Loads configured external calendar sources from athlete profile."""
        if not self.config_path.exists():
            return []
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            integrations = data.get("preferences", {}).get("integrations", {})
            return integrations.get("external_calendars", [])
        except Exception:
            return []

    # --------------------------------------------------------------------------
    # 2. Feed Fetching with Local Cache
    # --------------------------------------------------------------------------
    def fetch_feed(self, url: str, timeout: int = 15, force_refresh: bool = False, cache_ttl_min: int = 15) -> str:
        """
        Fetches iCal feed content with local disk caching.
        Handles both 'webcal://' and 'https://' URLs.
        """
        clean_url = url.strip()
        if clean_url.startswith("webcal://"):
            clean_url = "https://" + clean_url[len("webcal://"):]

        cache_key = hashlib.sha256(clean_url.encode("utf-8")).hexdigest()[:16]
        cache_file = self.cache_dir / f"feed_{cache_key}.ics"

        now = datetime.now(timezone.utc)
        if not force_refresh and cache_file.exists():
            mtime = datetime.fromtimestamp(cache_file.stat().st_mtime, tz=timezone.utc)
            if now - mtime < timedelta(minutes=cache_ttl_min):
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        return f.read()
                except Exception:
                    pass

        headers = {
            "User-Agent": "IntervalsICU-Coach-Engine/1.0 (Endurance Assistant)",
            "Accept": "text/calendar, text/plain, */*",
        }
        resp = requests.get(clean_url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        content = resp.text

        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            pass

        return content

    # --------------------------------------------------------------------------
    # 3. Deterministic iCal Parser (RFC 5545)
    # --------------------------------------------------------------------------
    def parse_datetime(self, dt_raw: str, dt_key: str = "") -> Tuple[datetime, bool]:
        """
        Parses iCal DTSTART/DTEND string into a timezone-aware datetime in athlete local TZ.
        Returns (datetime, is_all_day).
        """
        raw = dt_raw.strip()
        # All-day date (YYYYMMDD)
        if len(raw) == 8 and raw.isdigit():
            d = datetime.strptime(raw, "%Y%m%d").date()
            start_dt = datetime.combine(d, dt_time.min, tzinfo=self.tz)
            return start_dt, True

        # UTC format with Z (YYYYMMDDTHHMMSSZ)
        if raw.endswith("Z"):
            dt = datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            return dt.astimezone(self.tz), False

        # Custom TZID in key (e.g. DTSTART;TZID=Europe/Rome:20260916T120000)
        target_tz = self.tz
        if "TZID=" in dt_key.upper():
            try:
                tz_part = dt_key.split("TZID=")[1].split(";")[0].split(":")[0].strip()
                target_tz = ZoneInfo(tz_part)
            except Exception:
                target_tz = self.tz

        dt = datetime.strptime(raw, "%Y%m%dT%H%M%S").replace(tzinfo=target_tz)
        return dt.astimezone(self.tz), False

    def parse_ical(
        self,
        content: str,
        cal_name: str,
        cal_type: str = "personal",
        default_commute_minutes: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Parses iCal content into standardized event dictionaries.
        Unfolds RFC 5545 multi-line attributes and unescapes text.
        """
        # Unfold lines (RFC 5545: a line starting with space or tab is a continuation)
        unfolded = re.sub(r"\r?\n[ \t]", "", content)
        lines = unfolded.splitlines()

        events: List[Dict[str, Any]] = []
        in_event = False
        curr: Dict[str, Any] = {}

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line == "BEGIN:VEVENT":
                in_event = True
                curr = {
                    "calendar_name": cal_name,
                    "calendar_type": cal_type,
                    "commute_minutes": default_commute_minutes,
                }
            elif line == "END:VEVENT":
                in_event = False
                if "summary" in curr and "dtstart_raw" in curr:
                    try:
                        start_dt, all_day = self.parse_datetime(curr["dtstart_raw"], curr.get("dtstart_key", ""))
                        curr["start_dt"] = start_dt
                        curr["all_day"] = all_day

                        if "dtend_raw" in curr:
                            end_dt, _ = self.parse_datetime(curr["dtend_raw"], curr.get("dtend_key", ""))
                            curr["end_dt"] = end_dt
                        else:
                            curr["end_dt"] = start_dt + (timedelta(days=1) if all_day else timedelta(hours=1))

                        # Categorization
                        summ_lower = curr["summary"].lower()
                        if any(k in summ_lower for k in ["esame", "exam", "laurea", "tesi"]):
                            curr["category"] = "exam"
                            curr["is_blocking"] = True
                        elif any(k in summ_lower for k in ["treno", "train", "viaggio", "volo", "flight"]):
                            curr["category"] = "travel"
                            curr["is_blocking"] = True
                        elif cal_type == "university" or any(k in summ_lower for k in ["lezion", "aula", "corso", "lab"]):
                            curr["category"] = "lecture"
                            curr["is_blocking"] = False
                            if default_commute_minutes == 0:
                                curr["commute_minutes"] = 45
                        else:
                            curr["category"] = "personal"
                            curr["is_blocking"] = False

                        events.append(curr)
                    except Exception:
                        pass
                curr = {}
            elif in_event:
                if ":" in line:
                    key_part, val = line.split(":", 1)
                    key = key_part.split(";")[0].upper()
                    # Clean escaped chars
                    val_clean = (
                        val.replace(r"\,", ",")
                        .replace(r"\;", ";")
                        .replace(r"\n", "\n")
                        .replace(r"\\", "\\")
                    )

                    if key == "SUMMARY":
                        curr["summary"] = val_clean
                    elif key == "LOCATION":
                        curr["location"] = val_clean
                    elif key == "DESCRIPTION":
                        curr["description"] = val_clean
                    elif key == "UID":
                        curr["uid"] = val_clean
                    elif key == "DTSTART":
                        curr["dtstart_raw"] = val
                        curr["dtstart_key"] = key_part
                    elif key == "DTEND":
                        curr["dtend_raw"] = val
                        curr["dtend_key"] = key_part
                    elif key == "RRULE":
                        curr["rrule"] = val

        return events

    # --------------------------------------------------------------------------
    # 4. Multi-Feed Aggregation & Filtering
    # --------------------------------------------------------------------------
    def get_events(
        self,
        start_date: Union[str, date, datetime],
        end_date: Union[str, date, datetime],
        force_refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """Retrieves and aggregates all external calendar events in the date window."""
        s_date = (
            start_date.date() if isinstance(start_date, datetime)
            else datetime.strptime(start_date, "%Y-%m-%d").date() if isinstance(start_date, str)
            else start_date
        )
        e_date = (
            end_date.date() if isinstance(end_date, datetime)
            else datetime.strptime(end_date, "%Y-%m-%d").date() if isinstance(end_date, str)
            else end_date
        )

        sources = self.get_calendar_sources()
        all_events: List[Dict[str, Any]] = []

        for src in sources:
            if not src.get("enabled", True):
                continue
            url = src.get("url")
            if not url:
                continue
            name = src.get("name", "External Calendar")
            c_type = src.get("type", "personal")
            commute = src.get("commute_minutes", 45 if c_type == "university" else 0)

            try:
                content = self.fetch_feed(url, force_refresh=force_refresh)
                evs = self.parse_ical(content, cal_name=name, cal_type=c_type, default_commute_minutes=commute)
                all_events.extend(evs)
            except Exception as e:
                # Keep other calendars working if one feed fails
                continue

        # Filter by date range
        filtered = [
            e for e in all_events
            if s_date <= e["start_dt"].date() <= e_date or s_date <= e["end_dt"].date() <= e_date
        ]
        filtered.sort(key=lambda x: x["start_dt"])
        return filtered

    # --------------------------------------------------------------------------
    # 5. Daily Schedule & Training Window Solver
    # --------------------------------------------------------------------------
    def get_daily_schedule(
        self,
        target_date: Union[str, date, datetime],
        commute_override_min: Optional[int] = None,
        wake_time_override: Optional[str] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Analyzes a specific day's commitments, applies commute buffers,
        and computes all free time windows available for workouts.
        Respects athlete sleep routine (bedtime 00:00, 09:30 wake-up on afternoon class days).
        """
        t_date = (
            target_date.date() if isinstance(target_date, datetime)
            else datetime.strptime(target_date, "%Y-%m-%d").date() if isinstance(target_date, str)
            else target_date
        )

        day_events = self.get_events(t_date, t_date, force_refresh=force_refresh)
        # Filter only events that fall on this day
        day_events = [e for e in day_events if e["start_dt"].date() == t_date or e["end_dt"].date() == t_date]

        # Determine wake-up time based on afternoon classes rule
        profile_routine = {}
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    prof_data = json.load(f)
                profile_routine = prof_data.get("preferences", {}).get("integrations", {}).get("sleep_and_routine", {})
            except Exception:
                pass

        wake_std_str = profile_routine.get("wake_up_standard", "08:00")
        wake_flex_str = profile_routine.get("wake_up_standard_flexible", "08:30")
        wake_afternoon_str = profile_routine.get("wake_up_afternoon_classes", "09:30")

        has_morning_events = any(not e.get("all_day") and e["start_dt"].hour < 12 for e in day_events)
        has_afternoon_classes = any(e.get("category") == "lecture" and e["start_dt"].hour >= 12 for e in day_events)

        if wake_time_override:
            w_h, w_m = map(int, wake_time_override.split(":"))
            wake_time = dt_time(hour=w_h, minute=w_m)
            routine_reason = "override"
        elif has_afternoon_classes and not has_morning_events:
            w_h, w_m = map(int, wake_afternoon_str.split(":"))
            wake_time = dt_time(hour=w_h, minute=w_m)
            routine_reason = "afternoon_classes_sleep_in"
        else:
            # Flexible standard wake-up: 08:00 if early morning commitment (before 10:15), else 08:30
            has_early_morning = any(
                not e.get("all_day") and (e["start_dt"] - timedelta(minutes=e.get("commute_minutes", 0))).time() < dt_time(10, 15)
                for e in day_events
            )
            target_str = wake_std_str if has_early_morning else wake_flex_str
            w_h, w_m = map(int, target_str.split(":"))
            wake_time = dt_time(hour=w_h, minute=w_m)
            routine_reason = "standard_early" if has_early_morning else "standard_flexible_sleep_in"

        day_start = datetime.combine(t_date, wake_time, tzinfo=self.tz)
        day_end = datetime.combine(t_date, dt_time(hour=22, minute=0), tzinfo=self.tz)

        has_all_day_block = any(e.get("all_day", False) or e.get("category") == "exam" for e in day_events)

        busy_blocks: List[Dict[str, Any]] = []
        for e in day_events:
            commute = commute_override_min if commute_override_min is not None else e.get("commute_minutes", 0)
            c_delta = timedelta(minutes=commute)

            raw_start = e["start_dt"]
            raw_end = e["end_dt"]

            # Bounded start & end with travel time
            eff_start = max(day_start, raw_start - c_delta if not e["all_day"] else day_start)
            eff_end = min(day_end, raw_end + c_delta if not e["all_day"] else day_end)

            busy_blocks.append({
                "summary": e["summary"],
                "category": e.get("category", "personal"),
                "calendar_name": e.get("calendar_name", ""),
                "location": e.get("location", ""),
                "raw_start": raw_start.strftime("%H:%M"),
                "raw_end": raw_end.strftime("%H:%M"),
                "effective_start": eff_start.strftime("%H:%M"),
                "effective_end": eff_end.strftime("%H:%M"),
                "effective_start_dt": eff_start,
                "effective_end_dt": eff_end,
                "commute_minutes": commute,
            })

        # Merge overlapping busy blocks
        busy_blocks.sort(key=lambda x: x["effective_start_dt"])
        merged_busy: List[Tuple[datetime, datetime]] = []
        for b in busy_blocks:
            s = b["effective_start_dt"]
            e = b["effective_end_dt"]
            if not merged_busy:
                merged_busy.append((s, e))
            else:
                last_s, last_e = merged_busy[-1]
                if s <= last_e:
                    merged_busy[-1] = (last_s, max(last_e, e))
                else:
                    merged_busy.append((s, e))

        # Calculate free windows between day_start and day_end
        free_windows: List[Dict[str, Any]] = []
        curr_ptr = day_start
        for b_s, b_e in merged_busy:
            if b_s > curr_ptr:
                dur_min = int((b_s - curr_ptr).total_seconds() // 60)
                if dur_min >= 20:
                    free_windows.append({
                        "start": curr_ptr.strftime("%H:%M"),
                        "end": b_s.strftime("%H:%M"),
                        "duration_minutes": dur_min,
                        "slot": "morning" if curr_ptr.hour < 12 else "afternoon" if curr_ptr.hour < 18 else "evening",
                    })
            curr_ptr = max(curr_ptr, b_e)

        if curr_ptr < day_end:
            dur_min = int((day_end - curr_ptr).total_seconds() // 60)
            if dur_min >= 20:
                free_windows.append({
                    "start": curr_ptr.strftime("%H:%M"),
                    "end": day_end.strftime("%H:%M"),
                    "duration_minutes": dur_min,
                    "slot": "morning" if curr_ptr.hour < 12 else "afternoon" if curr_ptr.hour < 18 else "evening",
                })

        return {
            "date": t_date.isoformat(),
            "wake_up_time": wake_time.strftime("%H:%M"),
            "bedtime": "00:00",
            "routine_applied": routine_reason,
            "has_all_day_block": has_all_day_block,
            "events_count": len(day_events),
            "events": [
                {
                    "summary": e["summary"],
                    "calendar": e["calendar_name"],
                    "start": e["start_dt"].strftime("%H:%M") if not e["all_day"] else "All Day",
                    "end": e["end_dt"].strftime("%H:%M") if not e["all_day"] else "All Day",
                    "location": e.get("location", ""),
                    "category": e.get("category", "personal"),
                }
                for e in day_events
            ],
            "busy_blocks": [
                {k: v for k, v in b.items() if not k.endswith("_dt")} for b in busy_blocks
            ],
            "free_windows": free_windows,
        }

    def find_optimal_training_slot(
        self,
        target_date: Union[str, date, datetime],
        workout_duration_min: int,
        shower_buffer_min: int = 35,
        preference: str = "morning",
        wake_time_override: Optional[str] = None,
        is_hard_workout: bool = False,
        prefer_pre_meal: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """
        Finds the best available time slot on target_date that fits
        the workout duration plus the post-workout shower/recovery buffer.
        Respects athlete meal digestion rules (>= 2h post-meal, pre-meal preferred for hard workouts).
        """
        schedule = self.get_daily_schedule(target_date, wake_time_override=wake_time_override)
        if schedule.get("has_all_day_block"):
            return None

        total_needed = workout_duration_min + shower_buffer_min
        windows = schedule.get("free_windows", [])
        viable = [w for w in windows if w["duration_minutes"] >= total_needed]

        if not viable:
            return None

        # Prioritize based on preference and pre-meal timing
        def slot_priority(w: Dict[str, Any]) -> Tuple[int, int, int]:
            slot_match = 0 if w["slot"] == preference else 1
            s_h, s_m = map(int, w["start"].split(":"))
            start_mins = s_h * 60 + s_m

            # Pre-meal priority for hard workouts
            meal_priority = 1
            if is_hard_workout and prefer_pre_meal:
                wake_h, wake_m = map(int, schedule["wake_up_time"].split(":"))
                wake_mins = wake_h * 60 + wake_m
                # Pre-breakfast: right at wake-up
                is_pre_breakfast = abs(start_mins - wake_mins) <= 45
                # Pre-lunch: starts 11:30 - 13:00
                is_pre_lunch = 11 * 60 + 30 <= start_mins <= 13 * 60
                # Pre-dinner: starts 17:30 - 19:30
                is_pre_dinner = 17 * 60 + 30 <= start_mins <= 19 * 60 + 30

                if is_pre_breakfast or is_pre_lunch or is_pre_dinner:
                    meal_priority = 0
                else:
                    meal_priority = 2

            return (slot_match, meal_priority, start_mins if preference != "evening" else -w["duration_minutes"])

        viable.sort(key=slot_priority)
        chosen = viable[0]

        win_start_dt = datetime.strptime(f"{schedule['date']} {chosen['start']}", "%Y-%m-%d %H:%M")
        rec_start_dt = win_start_dt
        rec_end_dt = rec_start_dt + timedelta(minutes=workout_duration_min)

        start_h = rec_start_dt.hour
        wake_h, wake_m = map(int, schedule["wake_up_time"].split(":"))
        wake_mins = wake_h * 60 + wake_m
        run_mins = start_h * 60 + rec_start_dt.minute

        # Construct meal / digestion guidance
        if is_hard_workout:
            if abs(run_mins - wake_mins) <= 60:
                meal_advice = (
                    "PRE-BREAKFAST FASTED (Consigliato): Allenati PRIMA della colazione (a digiuno, idratazione leggera con acqua/elettroliti). "
                    "Se invece consumi la colazione al risveglio, attendi almeno 2 ore piene (120+ min) prima di avviare la sessione tosta."
                )
                timing_type = "pre_breakfast"
            elif 11 <= start_h <= 13:
                meal_advice = (
                    "PRE-PRANZO (Consigliato): Allenati PRIMA del pranzo. Consuma il pasto post-doccia e recupero."
                )
                timing_type = "pre_lunch"
            elif 14 <= start_h <= 17:
                meal_advice = (
                    "POST-PRANZO (Attesa digestione >= 2h): Assicurati di aver terminato il pranzo almeno 2 ore piene (o più) prima della sessione tosta."
                )
                timing_type = "post_lunch_digestion"
            elif 17 < start_h <= 20:
                meal_advice = (
                    "PRE-CENA (Consigliato): Allenati PRIMA di cena (lontano dal pranzo o da spuntini pesanti). Cena dopo doccia e recupero."
                )
                timing_type = "pre_dinner"
            else:
                meal_advice = (
                    "ATTENZIONE DIGESTIONE: Mantieni almeno 2 ore piene (o più) di distanza da qualsiasi pasto precedente (colazione inclusa)."
                )
                timing_type = "general_meal_buffer"
        else:
            meal_advice = (
                "SESSIONE AGILE: Impatto digestivo moderato. Consigliato comunque correre prima del pasto oppure attendere 45-60 min di digestione se hai mangiato."
            )
            timing_type = "easy_buffer"

        return {
            "date": schedule["date"],
            "recommended_start": rec_start_dt.strftime("%H:%M"),
            "recommended_end": rec_end_dt.strftime("%H:%M"),
            "post_workout_ready": (rec_end_dt + timedelta(minutes=shower_buffer_min)).strftime("%H:%M"),
            "window": chosen,
            "margin_minutes": chosen["duration_minutes"] - total_needed,
            "is_hard_workout": is_hard_workout,
            "timing_type": timing_type,
            "meal_advice": meal_advice,
        }

    # --------------------------------------------------------------------------
    # 6. Synchronization with MemoryManager
    # --------------------------------------------------------------------------
    def sync_to_memory_manager(
        self,
        memory_manager: Any,
        days_ahead: int = 30,
        force_refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Synchronizes upcoming external calendar commitments directly into MemoryManager.
        Registers non-training days and dynamic lecture busy windows.
        """
        today = datetime.now(self.tz).date()
        end = today + timedelta(days=days_ahead)

        events = self.get_events(today, end, force_refresh=force_refresh)
        imported: List[Dict[str, Any]] = []

        for e in events:
            summary = e.get("summary", "")
            cat = e.get("category", "personal")
            start_date_str = e["start_dt"].date().isoformat()
            end_date_str = e["end_dt"].date().isoformat()

            # Determine constraint action
            if cat == "exam" or e.get("all_day"):
                action = "no_training"
            elif cat in ["lecture", "travel"]:
                action = "busy_window"
            else:
                action = "available"

            time_desc = (
                f"{e['start_dt'].strftime('%H:%M')}-{e['end_dt'].strftime('%H:%M')}"
                if not e.get("all_day") else "All-Day"
            )
            full_desc = f"[{e.get('calendar_name')}] {summary} ({time_desc})"

            c = memory_manager.add_calendar_constraint(
                date_start=start_date_str,
                date_end=end_date_str,
                description=full_desc,
                constraint_type=cat,
                action=action,
                sync_intervals=False,  # Keep Intervals.icu clean to prevent duplicate loop!
            )
            imported.append(c)

        return imported


def get_external_calendar_manager() -> ExternalCalendarManager:
    """Factory helper returning singleton-like ExternalCalendarManager."""
    return ExternalCalendarManager()

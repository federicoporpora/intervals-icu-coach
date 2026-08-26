"""
Deterministic State and Profile Staleness Manager
==================================================
Manages athlete onboarding state, profile metrics persistence,
and TTL-based metric staleness validation.
"""

import os
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union


class StateManager:
    """Manages athlete profile data, staleness TTL checks, and onboarding initialization."""

    def __init__(
        self,
        profile_path: Optional[Union[str, Path]] = None,
        staleness_rules_path: Optional[Union[str, Path]] = None,
    ):
        base_dir = Path(__file__).resolve().parent.parent
        self.profile_path = Path(profile_path) if profile_path else base_dir / "config" / "athlete_profile.json"
        self.staleness_rules_path = (
            Path(staleness_rules_path) if staleness_rules_path else base_dir / "config" / "staleness_rules.json"
        )

    @staticmethod
    def current_iso_timestamp() -> str:
        """Returns the current ISO 8601 UTC timestamp."""
        return datetime.now(timezone.utc).isoformat()

    def get_profile(self) -> Dict[str, Any]:
        """Loads and returns the athlete profile JSON."""
        if not self.profile_path.exists():
            return {"initialized": False}
        with open(self.profile_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_profile(self, profile: Dict[str, Any]) -> None:
        """Saves the athlete profile JSON to disk."""
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.profile_path, "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2)

    def get_staleness_rules(self) -> Dict[str, int]:
        """Loads the metric staleness TTL rules in days."""
        if not self.staleness_rules_path.exists():
            return {
                "weight_kg": 14,
                "resting_hr_baseline": 30,
                "lthr_bpm": 60,
                "threshold_pace_sec_km": 45,
                "max_hr_bpm": 90,
                "target_events": 30,
                "weekly_availability": 30,
            }
        with open(self.staleness_rules_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def is_initialized(self) -> bool:
        """Returns True if the athlete profile is initialized, False otherwise."""
        profile = self.get_profile()
        return bool(profile.get("initialized", False))

    def _parse_timestamp(self, ts_str: Optional[str]) -> Optional[datetime]:
        """Parses ISO 8601 timestamp string into a timezone-aware UTC datetime."""
        if not ts_str or not isinstance(ts_str, str) or not ts_str.strip():
            return None
        try:
            # Replace Z with +00:00 for compatibility
            clean_ts = ts_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None

    def get_stale_metrics(self, current_time: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        Compares current system date with updated_at timestamps against staleness_rules.json.
        Returns a list of stale metric descriptors.
        """
        profile = self.get_profile()
        if not profile.get("initialized", False):
            return []

        rules = self.get_staleness_rules()
        now = current_time or datetime.now(timezone.utc)
        stale_metrics = []

        # Mapping of rule keys to profile lookup functions
        def check_field(field_name: str, updated_at_str: Optional[str], current_val: Any):
            ttl_days = rules.get(field_name, 30)
            parsed_dt = self._parse_timestamp(updated_at_str)
            
            if parsed_dt is None:
                stale_metrics.append({
                    "field": field_name,
                    "ttl_days": ttl_days,
                    "days_since_update": None,
                    "current_value": current_val,
                    "last_updated": None,
                    "reason": "Timestamp missing or never updated",
                })
                return

            age_days = (now - parsed_dt).total_seconds() / 86400.0
            if age_days > ttl_days:
                stale_metrics.append({
                    "field": field_name,
                    "ttl_days": ttl_days,
                    "days_since_update": round(age_days, 1),
                    "current_value": current_val,
                    "last_updated": parsed_dt.isoformat(),
                    "reason": f"Exceeded TTL ({round(age_days, 1)}d > {ttl_days}d)",
                })

        # 1. weight_kg
        weight_obj = profile.get("personal", {}).get("weight_kg", {})
        check_field("weight_kg", weight_obj.get("updated_at"), weight_obj.get("value"))

        # 2. resting_hr_baseline
        rhr_obj = profile.get("metrics", {}).get("resting_hr_baseline", {})
        check_field("resting_hr_baseline", rhr_obj.get("updated_at"), rhr_obj.get("value"))

        # 3. lthr_bpm
        lthr_obj = profile.get("metrics", {}).get("lthr_bpm", {})
        check_field("lthr_bpm", lthr_obj.get("updated_at"), lthr_obj.get("value"))

        # 4. threshold_pace_sec_km
        t_pace_obj = profile.get("metrics", {}).get("threshold_pace_sec_km", {})
        check_field("threshold_pace_sec_km", t_pace_obj.get("updated_at"), t_pace_obj.get("value"))

        # 5. max_hr_bpm
        max_hr_obj = profile.get("metrics", {}).get("max_hr_bpm", {})
        check_field("max_hr_bpm", max_hr_obj.get("updated_at"), max_hr_obj.get("value"))

        # 6. weekly_availability
        avail_obj = profile.get("preferences", {}).get("weekly_availability", {})
        check_field("weekly_availability", avail_obj.get("updated_at"), avail_obj.get("days"))

        # 7. target_events
        events = profile.get("target_events", [])
        if events and isinstance(events, list):
            # Check the most recently updated event or first event timestamp
            first_event = events[0]
            check_field("target_events", first_event.get("updated_at"), [e.get("name") for e in events])
        else:
            check_field("target_events", None, [])

        return stale_metrics

    # --------------------------------------------------------------------------
    # Zone Calculations
    # --------------------------------------------------------------------------
    @staticmethod
    def calculate_hr_zones(lthr: int, max_hr: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Calculates 5-zone HR model based on Joe Friel / Coggan LTHR model.
        Z1: < 81% LTHR
        Z2: 81-89% LTHR
        Z3: 90-93% LTHR
        Z4: 94-99% LTHR
        Z5: 100%+ LTHR (capped at max_hr if provided)
        """
        if not lthr or lthr <= 0:
            if max_hr and max_hr > 0:
                # Estimate LTHR as ~88% of Max HR
                lthr = int(round(max_hr * 0.88))
            else:
                return []

        z1_max = int(round(lthr * 0.80))
        z2_min = z1_max + 1
        z2_max = int(round(lthr * 0.89))
        z3_min = z2_max + 1
        z3_max = int(round(lthr * 0.93))
        z4_min = z3_max + 1
        z4_max = int(round(lthr * 0.99))
        z5_min = lthr
        z5_max = max_hr if max_hr and max_hr > z5_min else int(round(lthr * 1.08))

        return [
            {"zone": "Z1", "name": "Active Recovery", "min": 0, "max": z1_max},
            {"zone": "Z2", "name": "Aerobic / Endurance", "min": z2_min, "max": z2_max},
            {"zone": "Z3", "name": "Tempo", "min": z3_min, "max": z3_max},
            {"zone": "Z4", "name": "Threshold (LT2)", "min": z4_min, "max": z4_max},
            {"zone": "Z5", "name": "VO2max / Anaerobic", "min": z5_min, "max": z5_max},
        ]

    @staticmethod
    def calculate_pace_zones(threshold_pace_sec_km: float) -> List[Dict[str, Any]]:
        """
        Calculates 6-zone Running Pace model relative to Threshold Pace (100%).
        Pace in seconds/km (lower seconds = faster pace).
        """
        if not threshold_pace_sec_km or threshold_pace_sec_km <= 0:
            return []

        t = float(threshold_pace_sec_km)
        
        # Z1 Recovery: > 125% of T-pace
        # Z2 Easy: 115% - 124% of T-pace
        # Z3 Marathon / Steady: 106% - 114% of T-pace
        # Z4 Threshold: 98% - 105% of T-pace
        # Z5 VO2max / Interval: 90% - 97% of T-pace
        # Z6 Repetition / Speed: < 89% of T-pace
        return [
            {
                "zone": "Z1",
                "name": "Active Recovery",
                "min_sec_km": round(t * 1.25, 1),
                "max_sec_km": 999.0,
                "pct_threshold": "< 80% velocity",
            },
            {
                "zone": "Z2",
                "name": "Easy Aerobic",
                "min_sec_km": round(t * 1.15, 1),
                "max_sec_km": round(t * 1.24, 1),
                "pct_threshold": "80-87% velocity",
            },
            {
                "zone": "Z3",
                "name": "Marathon / Steady",
                "min_sec_km": round(t * 1.06, 1),
                "max_sec_km": round(t * 1.14, 1),
                "pct_threshold": "88-94% velocity",
            },
            {
                "zone": "Z4",
                "name": "Threshold (LT2)",
                "min_sec_km": round(t * 0.98, 1),
                "max_sec_km": round(t * 1.05, 1),
                "pct_threshold": "95-102% velocity",
            },
            {
                "zone": "Z5",
                "name": "VO2max / Interval",
                "min_sec_km": round(t * 0.90, 1),
                "max_sec_km": round(t * 0.97, 1),
                "pct_threshold": "103-111% velocity",
            },
            {
                "zone": "Z6",
                "name": "Repetition / Speed",
                "min_sec_km": 0.0,
                "max_sec_km": round(t * 0.89, 1),
                "pct_threshold": "> 112% velocity",
            },
        ]

    # --------------------------------------------------------------------------
    # Profile Mutation & Initialization
    # --------------------------------------------------------------------------
    def initialize_profile(self, onboarding_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Seeds athlete profile from onboarding questionnaire data, computes zones,
        initializes all timestamps to now, and marks initialized = True.
        """
        now_iso = self.current_iso_timestamp()
        
        weight = float(onboarding_data.get("weight_kg", 0.0))
        lthr = int(onboarding_data.get("lthr_bpm", 0))
        max_hr = int(onboarding_data.get("max_hr_bpm", 0))
        resting_hr = int(onboarding_data.get("resting_hr_baseline", 0))
        threshold_pace = float(onboarding_data.get("threshold_pace_sec_km", 0.0))

        # Calculate zones deterministically
        hr_zones = self.calculate_hr_zones(lthr, max_hr)
        pace_zones = self.calculate_pace_zones(threshold_pace)

        # Build target events
        raw_events = onboarding_data.get("target_events", [])
        formatted_events = []
        for ev in raw_events:
            ev_copy = dict(ev)
            ev_copy["updated_at"] = now_iso
            formatted_events.append(ev_copy)

        # Availability
        weekly_avail = onboarding_data.get("weekly_availability", {
            "monday": "Rest or short recovery",
            "tuesday": "Intervals",
            "wednesday": "Easy aerobic",
            "thursday": "Tempo/Threshold",
            "friday": "Rest",
            "saturday": "Long Run",
            "sunday": "Cross-training or Easy"
        })

        profile = {
            "initialized": True,
            "personal": {
                "name": onboarding_data.get("name", "Athlete"),
                "birth_date": onboarding_data.get("birth_date", ""),
                "weight_kg": {"value": weight, "updated_at": now_iso},
            },
            "metrics": {
                "lthr_bpm": {"value": lthr, "updated_at": now_iso},
                "max_hr_bpm": {"value": max_hr, "updated_at": now_iso},
                "resting_hr_baseline": {"value": resting_hr, "updated_at": now_iso},
                "threshold_pace_sec_km": {"value": threshold_pace, "updated_at": now_iso},
                "hr_zones": hr_zones,
                "pace_zones": pace_zones,
            },
            "preferences": {
                "coaching_philosophy": onboarding_data.get("coaching_philosophy", "Polarized 80/20"),
                "strengths": onboarding_data.get("strengths", []),
                "weaknesses": onboarding_data.get("weaknesses", []),
                "weekly_availability": {
                    "days": weekly_avail,
                    "updated_at": now_iso,
                },
            },
            "target_events": formatted_events,
        }

        self.save_profile(profile)
        return profile

    def update_profile(self, updates_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Updates specific fields in the athlete profile and updates their timestamps to now.
        Handles flat or nested dictionary keys.
        """
        profile = self.get_profile()
        now_iso = self.current_iso_timestamp()

        # Update personal fields
        if "name" in updates_dict:
            profile.setdefault("personal", {})["name"] = updates_dict["name"]
        if "birth_date" in updates_dict:
            profile.setdefault("personal", {})["birth_date"] = updates_dict["birth_date"]
        if "weight_kg" in updates_dict:
            val = float(updates_dict["weight_kg"])
            profile.setdefault("personal", {})["weight_kg"] = {"value": val, "updated_at": now_iso}

        # Update metrics
        recalc_hr = False
        recalc_pace = False

        if "lthr_bpm" in updates_dict:
            val = int(updates_dict["lthr_bpm"])
            profile.setdefault("metrics", {})["lthr_bpm"] = {"value": val, "updated_at": now_iso}
            recalc_hr = True
        if "max_hr_bpm" in updates_dict:
            val = int(updates_dict["max_hr_bpm"])
            profile.setdefault("metrics", {})["max_hr_bpm"] = {"value": val, "updated_at": now_iso}
            recalc_hr = True
        if "resting_hr_baseline" in updates_dict:
            val = int(updates_dict["resting_hr_baseline"])
            profile.setdefault("metrics", {})["resting_hr_baseline"] = {"value": val, "updated_at": now_iso}
        if "threshold_pace_sec_km" in updates_dict:
            val = float(updates_dict["threshold_pace_sec_km"])
            profile.setdefault("metrics", {})["threshold_pace_sec_km"] = {"value": val, "updated_at": now_iso}
            recalc_pace = True

        if recalc_hr:
            lthr = profile.get("metrics", {}).get("lthr_bpm", {}).get("value", 0)
            max_hr = profile.get("metrics", {}).get("max_hr_bpm", {}).get("value", 0)
            profile["metrics"]["hr_zones"] = self.calculate_hr_zones(lthr, max_hr)

        if recalc_pace:
            t_pace = profile.get("metrics", {}).get("threshold_pace_sec_km", {}).get("value", 0.0)
            profile["metrics"]["pace_zones"] = self.calculate_pace_zones(t_pace)

        # Update preferences
        if "coaching_philosophy" in updates_dict:
            profile.setdefault("preferences", {})["coaching_philosophy"] = updates_dict["coaching_philosophy"]
        if "strengths" in updates_dict:
            profile.setdefault("preferences", {})["strengths"] = updates_dict["strengths"]
        if "weaknesses" in updates_dict:
            profile.setdefault("preferences", {})["weaknesses"] = updates_dict["weaknesses"]
        if "weekly_availability" in updates_dict:
            profile.setdefault("preferences", {})["weekly_availability"] = {
                "days": updates_dict["weekly_availability"],
                "updated_at": now_iso,
            }

        # Update events
        if "target_events" in updates_dict:
            formatted_events = []
            for ev in updates_dict["target_events"]:
                ev_copy = dict(ev)
                ev_copy["updated_at"] = now_iso
                formatted_events.append(ev_copy)
            profile["target_events"] = formatted_events

        self.save_profile(profile)
        return profile


# Default singleton factory
def get_state_manager() -> StateManager:
    return StateManager()

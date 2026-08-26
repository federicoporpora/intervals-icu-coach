"""
Intervals.icu Structured Workout and Training Plan Generator
============================================================
Generates deterministic, syntax-compliant workout descriptions for Intervals.icu.
Supports running (Pace/HR/Zones) and cycling (Power/FTP/HR/Zones), workout templates,
and autonomic dynamic plan adaptations.
"""

from typing import Dict, Any, List, Optional, Union
from datetime import datetime, date, timedelta
import re


class WorkoutPlanGenerator:
    """Generates structured workouts compliant with Intervals.icu calendar format."""

    @staticmethod
    def format_step(
        duration_or_dist: str,
        intensity: str,
        label: str = "",
        cadence_rpm: Optional[int] = None,
    ) -> str:
        """
        Formats an individual workout step.
        Examples:
          duration_or_dist: '10m', '1000m', '5km', '45s'
          intensity: '65% HR', '95% PACE', '90-95% LTHR', '88-94% FTP', 'Z2'
          label: 'Warmup', 'Threshold Cruise', 'Easy Spin'
        """
        step = f"- {duration_or_dist} {intensity}"
        if cadence_rpm:
            step += f" {cadence_rpm}rpm"
        if label:
            step += f" {label}"
        return step

    @classmethod
    def create_easy_aerobic_run(
        cls,
        duration_min: Optional[int] = None,
        distance_km: Optional[float] = None,
        target_hr_pct: int = 68,
        zone_label: str = "Z2 Aerobic Base",
        target_pace: Optional[str] = None,
        target_hr: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Creates a continuous steady Zone 2 base run supporting distance-based or duration-based syntax."""
        if distance_km is not None:
            main_km = max(1.0, round(distance_km - 1.5, 1))
            hr_str = target_hr or f"Z2 HR {target_hr_pct}% HR"
            pace_str = target_pace or "5:35-5:50 min/km"
            description = (
                f"Warmup\n"
                f"- 1km Z1 HR 5:50-6:10 min/km Riscaldamento (<145 bpm)\n\n"
                f"Main Set\n"
                f"- {main_km}km {hr_str} {pace_str} {zone_label}\n\n"
                f"Cooldown\n"
                f"- 0.5km Z1 HR 6:00-6:20 min/km Defaticamento (<145 bpm)"
            )
            return {
                "name": f"Corsa Facile Z2 (~{distance_km:.1f}k)",
                "type": "Run",
                "description": description,
                "category": "WORKOUT",
            }
        else:
            d = duration_min or 45
            description = (
                f"Warmup\n"
                f"- 10m 60-65% HR Easy Jog\n\n"
                f"Main Set\n"
                f"- {d - 15}m {target_hr_pct}% HR {zone_label}\n\n"
                f"Cooldown\n"
                f"- 5m 60% HR Walking / Easy Jog"
            )
            return {
                "name": f"Easy Aerobic Run {d}m",
                "type": "Run",
                "description": description,
                "category": "WORKOUT",
            }

    @classmethod
    def create_vo2max_intervals(
        cls,
        sport: str = "Run",
        reps: int = 5,
        rep_spec: str = "1km",
        rep_intensity: str = "95-100% PACE",
        recovery_spec: str = "2m",
        recovery_intensity: str = "60% HR",
        warmup_min: int = 15,
        cooldown_min: int = 10,
    ) -> Dict[str, Any]:
        """Creates a VO2max interval workout with repeats."""
        description = (
            f"Warmup\n"
            f"- {warmup_min}m 65% HR Progressive Warmup\n\n"
            f"Main Set\n"
            f"{reps}x\n"
            f"- {rep_spec} {rep_intensity} Fast Rep\n"
            f"- {recovery_spec} {recovery_intensity} Recovery Jog\n\n"
            f"Cooldown\n"
            f"- {cooldown_min}m 60-65% HR Easy Flush"
        )
        return {
            "name": f"{reps}x{rep_spec} VO2max Intervals",
            "type": sport,
            "description": description,
            "category": "WORKOUT",
        }

    @classmethod
    def create_threshold_tempo_session(
        cls,
        sport: str = "Run",
        blocks: int = 4,
        block_dist_km: float = 1.5,
        block_intensity: str = "Z4 HR 4:15-4:20 min/km",
        recovery_dist_km: float = 0.4,
        warmup_km: float = 2.0,
        cooldown_km: float = 1.0,
    ) -> Dict[str, Any]:
        """Creates a Lactate Threshold / Cruise Interval workout."""
        description = (
            f"Warmup\n"
            f"- {warmup_km}km Z1 HR 5:50-6:10 min/km Riscaldamento Progressivo (<145 bpm)\n\n"
            f"Allunghi 4x\n"
            f"- 0.1km Z5 HR 3:45-3:55 min/km Allungo\n"
            f"- 0.1km Z1 HR 6:00-6:30 min/km Souplesse\n\n"
            f"Main Set {blocks}x\n"
            f"- {block_dist_km}km {block_intensity} Ripetuta Soglia LT2 (177-188 bpm)\n"
            f"- {recovery_dist_km}km Z1 HR 6:00-6:30 min/km Recupero Souplesse (<145 bpm)\n\n"
            f"Cooldown\n"
            f"- {cooldown_km}km Z1 HR 5:50-6:15 min/km Defaticamento (<145 bpm)"
        )
        return {
            "name": f"⚡ Soglia: {blocks}x{block_dist_km}km",
            "type": sport,
            "description": description,
            "category": "WORKOUT",
        }

    @classmethod
    def create_progressive_long_run(
        cls,
        total_distance_km: float = 14.0,
        fast_finish_km: float = 2.0,
    ) -> Dict[str, Any]:
        """Creates an extended long run with a progression to Marathon / Moderate pace."""
        base_km = total_distance_km - fast_finish_km - 2.0
        description = (
            f"Warmup\n"
            f"- 1.5km Z1 HR 5:50-6:10 min/km Avvio Progressivo (<145 bpm)\n\n"
            f"Steady Aerobic\n"
            f"- {base_km}km Z2 HR 5:35-5:50 min/km Fondo Lento Base (146-164 bpm)\n\n"
            f"Progression Finish\n"
            f"- {fast_finish_km}km Z3 HR 4:55-5:10 min/km Finale Progressione Z3 (165-176 bpm)\n\n"
            f"Cooldown\n"
            f"- 0.5km Z1 HR 6:00-6:20 min/km Defaticamento (<145 bpm)"
        )
        return {
            "name": f"🏃 Lungo Progressivo (~{total_distance_km:.1f}k)",
            "type": "Run",
            "description": description,
            "category": "WORKOUT",
        }

    @classmethod
    def create_recovery_flush(
        cls,
        sport: str = "Run",
        duration_min: int = 30,
    ) -> Dict[str, Any]:
        """Creates a very light Zone 1 active recovery flush session."""
        description = (
            f"Active Recovery Flush\n"
            f"- {duration_min}m 55-62% HR Strict Zone 1 Recovery\n"
            f"- Keep HR strictly capped. Zero cardiac strain."
        )
        return {
            "name": f"Active Recovery Flush {duration_min}m",
            "type": sport,
            "description": description,
            "category": "WORKOUT",
        }

    @classmethod
    def create_sweet_spot_cycling(
        cls,
        reps: int = 3,
        rep_duration_min: int = 15,
        recovery_min: int = 5,
        warmup_min: int = 15,
        cooldown_min: int = 10,
    ) -> Dict[str, Any]:
        """Creates a cycling Sweet Spot (88-94% FTP) structured workout."""
        description = (
            f"Warmup\n"
            f"- {warmup_min}m 55-70% FTP Progressive Warmup\n\n"
            f"Sweet Spot Main Set\n"
            f"{reps}x\n"
            f"- {rep_duration_min}m 88-94% FTP 90rpm Sweet Spot\n"
            f"- {recovery_min}m 50% FTP 85rpm Recovery\n\n"
            f"Cooldown\n"
            f"- {cooldown_min}m 50% FTP Easy Spin"
        )
        return {
            "name": f"{reps}x{rep_duration_min}m Sweet Spot (Cycling)",
            "type": "Ride",
            "description": description,
            "category": "WORKOUT",
        }

    # --------------------------------------------------------------------------
    # Dynamic Plan Adaptations
    # --------------------------------------------------------------------------
    @classmethod
    def adapt_workout_for_readiness(
        cls,
        planned_workout: Dict[str, Any],
        readiness_status: str,
        athlete_profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Deterministically adapts a planned workout based on physiological readiness.
        
        Adaptation Rules:
        - RED: Autonomic strain / high illness risk -> Convert to 30m Active Recovery Z1 or Rest.
        - AMBER: Elevated fatigue -> Reduce volume by 30% or convert hard intervals to steady Z2.
        - GREEN: Execute full planned session without alteration.
        """
        sport = planned_workout.get("type", "Run")
        name = planned_workout.get("name", "Workout")
        
        if readiness_status == "GREEN":
            return {
                "adapted": False,
                "reason": "Optimal physiological readiness. Executing original workout.",
                "workout": planned_workout,
            }

        elif readiness_status == "RED":
            adapted_workout = cls.create_recovery_flush(sport=sport, duration_min=30)
            adapted_workout["start_date_local"] = planned_workout.get("start_date_local")
            adapted_workout["id"] = planned_workout.get("id")
            return {
                "adapted": True,
                "original_name": name,
                "action": "DOWNGRADED_TO_RECOVERY",
                "reason": "RED readiness status (suppressed HRV / elevated resting HR / severe fatigue). Converted high-strain session to 30m Z1 active recovery.",
                "workout": adapted_workout,
            }

        elif readiness_status == "AMBER":
            # If it's an interval workout, tone it down or convert to moderate Z2
            is_interval = any(kw in name.lower() for kw in ["interval", "vo2max", "threshold", "cruise", "tempo", "x"])
            
            if is_interval:
                # Convert to easy aerobic 45m Z2
                adapted_workout = cls.create_easy_aerobic_run(duration_min=45, target_hr_pct=68, zone_label="Z2 Aerobic - Fatigue Mitigation")
            else:
                # Reduce volume of base run by 25%
                adapted_workout = cls.create_easy_aerobic_run(duration_min=35, target_hr_pct=65, zone_label="Z1-Z2 Light Aerobic")
                
            adapted_workout["start_date_local"] = planned_workout.get("start_date_local")
            adapted_workout["id"] = planned_workout.get("id")
            adapted_workout["name"] = f"[Adapted] {adapted_workout['name']}"
            
            return {
                "adapted": True,
                "original_name": name,
                "action": "VOLUME_OR_INTENSITY_REDUCED",
                "reason": "AMBER readiness status (moderate fatigue). Scaled intensity back to Aerobic Zone 2 to prevent non-functional overreaching.",
                "workout": adapted_workout,
            }

        return {
            "adapted": False,
            "reason": f"Unknown readiness status: {readiness_status}. Keeping original plan.",
            "workout": planned_workout,
        }

    @classmethod
    def generate_calendar_payload(
        cls,
        workout_dict: Dict[str, Any],
        date_str: Union[str, date, datetime],
    ) -> Dict[str, Any]:
        """Prepares a full Intervals.icu event payload with proper timestamping."""
        if isinstance(date_str, datetime):
            start_iso = date_str.strftime("%Y-%m-%dT07:00:00")
        elif isinstance(date_str, date):
            start_iso = f"{date_str.strftime('%Y-%m-%d')}T07:00:00"
        else:
            start_iso = f"{str(date_str).split('T')[0]}T07:00:00"

        payload = {
            "category": "WORKOUT",
            "start_date_local": start_iso,
            "type": workout_dict.get("type", "Run"),
            "name": workout_dict.get("name", "Workout"),
            "description": workout_dict.get("description", ""),
        }
        if "id" in workout_dict:
            payload["id"] = workout_dict["id"]
        return payload

"""Coach Engine Tools Package"""
from .intervals_api import IntervalsAPIClient, IntervalsAPIError, get_intervals_client
from .workout_analyzer import (
    compute_aerobic_decoupling,
    analyze_lap_splits,
    analyze_interval_compliance,
    detect_fatigue_and_recovery_status,
    generate_workout_review_report,
    sec_to_pace_str,
    speed_to_pace_sec,
)
from .plan_generator import WorkoutPlanGenerator
from .state_manager import StateManager, get_state_manager

__all__ = [
    "IntervalsAPIClient",
    "IntervalsAPIError",
    "get_intervals_client",
    "compute_aerobic_decoupling",
    "analyze_lap_splits",
    "analyze_interval_compliance",
    "detect_fatigue_and_recovery_status",
    "generate_workout_review_report",
    "sec_to_pace_str",
    "speed_to_pace_sec",
    "WorkoutPlanGenerator",
    "StateManager",
    "get_state_manager",
]

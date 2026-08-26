"""
Coach Engine Command Line Interface
===================================
Provides quick deterministic terminal operations for state management,
activity review, and plan generation.
"""

import sys
import json
import argparse
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

from coach_engine.tools.state_manager import StateManager
from coach_engine.tools.intervals_api import IntervalsAPIClient
from coach_engine.tools.workout_analyzer import (
    compute_aerobic_decoupling,
    analyze_lap_splits,
    analyze_interval_compliance,
    detect_fatigue_and_recovery_status,
    generate_workout_review_report,
)
from coach_engine.tools.plan_generator import WorkoutPlanGenerator


def format_json(data: dict) -> str:
    return json.dumps(data, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Coach Engine CLI for Intervals.icu")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # 1. Status / Init Check
    subparsers.add_parser("status", help="Check initialization status and profile summary")

    # 2. Staleness Check
    subparsers.add_parser("staleness", help="Check for stale metrics against TTL rules")

    # 3. Onboarding Init
    init_parser = subparsers.add_parser("init", help="Initialize athlete profile with onboarding data")
    init_parser.add_argument("--name", required=True, help="Athlete name")
    init_parser.add_argument("--weight", type=float, required=True, help="Body weight in kg")
    init_parser.add_argument("--rhr", type=int, required=True, help="Resting HR baseline in bpm")
    init_parser.add_argument("--max-hr", type=int, required=True, help="Max HR in bpm")
    init_parser.add_argument("--lthr", type=int, required=True, help="LTHR in bpm")
    init_parser.add_argument("--threshold-pace-sec", type=float, required=True, help="Threshold pace in sec/km (e.g. 240 for 4:00/km)")
    init_parser.add_argument("--philosophy", default="Polarized 80/20", help="Coaching philosophy")

    # 4. Activity Review
    review_parser = subparsers.add_parser("review", help="Review and analyze a specific workout")
    review_parser.add_argument("--activity-id", required=True, help="Intervals.icu activity ID")
    review_parser.add_argument("--use-cache", action="store_true", help="Use local cached JSON if available")

    # 5. Readiness & Wellness Check
    readiness_parser = subparsers.add_parser("readiness", help="Check autonomic recovery and readiness")
    readiness_parser.add_argument("--days", type=int, default=7, help="Number of days to evaluate")

    # 6. Generate Workout
    plan_parser = subparsers.add_parser("generate-workout", help="Generate structured workout syntax")
    plan_parser.add_argument("--type", choices=["easy", "vo2max", "threshold", "long_run", "recovery", "sweet_spot"], default="vo2max")
    plan_parser.add_argument("--sport", choices=["Run", "Ride"], default="Run")
    plan_parser.add_argument("--duration", type=int, default=45, help="Duration in minutes")
    plan_parser.add_argument("--reps", type=int, default=5, help="Number of interval reps")

    args = parser.parse_args()

    sm = StateManager()
    api = IntervalsAPIClient()

    if args.command == "status":
        init = sm.is_initialized()
        profile = sm.get_profile()
        print(f"System Initialized: {init}")
        if init:
            print(f"Athlete: {profile.get('personal', {}).get('name')}")
            print(f"Coaching Philosophy: {profile.get('preferences', {}).get('coaching_philosophy')}")
            print(f"HR Zones: {len(profile.get('metrics', {}).get('hr_zones', []))} zones configured")
            print(f"Pace Zones: {len(profile.get('metrics', {}).get('pace_zones', []))} zones configured")
        else:
            print("Status: COLD-START REQUIRED. Profile uninitialized.")

    elif args.command == "staleness":
        if not sm.is_initialized():
            print("Profile is uninitialized. Run onboarding first.")
            return
        stale = sm.get_stale_metrics()
        if not stale:
            print("✅ All physiological metrics are fresh and within TTL bounds.")
        else:
            print("⚠️ Stale Metrics Detected:")
            for item in stale:
                print(f" - {item['field']}: {item['reason']} (TTL: {item['ttl_days']}d)")

    elif args.command == "init":
        onboarding_dict = {
            "name": args.name,
            "weight_kg": args.weight,
            "resting_hr_baseline": args.rhr,
            "max_hr_bpm": args.max_hr,
            "lthr_bpm": args.lthr,
            "threshold_pace_sec_km": args.threshold_pace_sec,
            "coaching_philosophy": args.philosophy,
        }
        profile = sm.initialize_profile(onboarding_dict)
        print("✅ Profile initialized successfully!")
        print(format_json(profile))

    elif args.command == "review":
        try:
            act = api.get_activity_details(args.activity_id, use_cache=args.use_cache)
            report = generate_workout_review_report(act)
            print(format_json(report))
        except Exception as e:
            print(f"Error reviewing activity {args.activity_id}: {e}")

    elif args.command == "readiness":
        try:
            today = date.today()
            oldest = today - timedelta(days=args.days)
            wellness = api.get_wellness(oldest, today)
            profile = sm.get_profile()
            readiness = detect_fatigue_and_recovery_status(wellness, profile.get("metrics"))
            print(format_json(readiness))
        except Exception as e:
            print(f"Error checking readiness: {e}")

    elif args.command == "generate-workout":
        if args.type == "easy":
            w = WorkoutPlanGenerator.create_easy_aerobic_run(duration_min=args.duration)
        elif args.type == "vo2max":
            w = WorkoutPlanGenerator.create_vo2max_intervals(sport=args.sport, reps=args.reps)
        elif args.type == "threshold":
            w = WorkoutPlanGenerator.create_threshold_tempo_session(sport=args.sport, blocks=args.reps)
        elif args.type == "long_run":
            w = WorkoutPlanGenerator.create_progressive_long_run(total_duration_min=args.duration)
        elif args.type == "recovery":
            w = WorkoutPlanGenerator.create_recovery_flush(sport=args.sport, duration_min=args.duration)
        elif args.type == "sweet_spot":
            w = WorkoutPlanGenerator.create_sweet_spot_cycling(reps=args.reps)
        print(format_json(w))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()

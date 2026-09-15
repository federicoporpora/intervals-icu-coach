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

# Ensure coach_engine is importable
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from coach_engine.tools.state_manager import StateManager

from coach_engine.tools.intervals_api import IntervalsAPIClient
from coach_engine.tools.memory_manager import MemoryManager
from coach_engine.tools.workout_analyzer import (
    compute_aerobic_decoupling,
    analyze_lap_splits,
    analyze_interval_compliance,
    detect_fatigue_and_recovery_status,
    generate_workout_review_report,
)
from coach_engine.tools.plan_generator import WorkoutPlanGenerator
from coach_engine.tools.external_calendar import ExternalCalendarManager


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
    init_parser.add_argument("--intervals-ical-sync", action="store_true", help="Enable Intervals.icu iCal feed sync")
    init_parser.add_argument("--external-calendar-sync", action="store_true", help="Enable reading personal commitments from Intervals.icu")
    init_parser.add_argument("--device-ecosystem", default="", help="Athlete device/watch ecosystem (e.g. Garmin, Suunto)")

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

    # 7. Memory Operations
    mem_parser = subparsers.add_parser("memory", help="Manage dual-horizon athlete memory")
    mem_subparsers = mem_parser.add_subparsers(dest="mem_action", help="Memory actions")

    mem_subparsers.add_parser("list", help="List all long-term and short-term memories")
    mem_subparsers.add_parser("prompt-context", help="Output formatted memory markdown for agent context")
    mem_subparsers.add_parser("prune", help="Prune expired constraints and temporary statuses")

    sync_c_parser = mem_subparsers.add_parser("sync-calendar", help="Sync calendar commitments and notes from Intervals.icu into active constraints")
    sync_c_parser.add_argument("--start", help="Start date (YYYY-MM-DD, defaults to today)")
    sync_c_parser.add_argument("--end", help="End date (YYYY-MM-DD, defaults to +60 days)")

    add_lt_parser = mem_subparsers.add_parser("add-long-term", help="Add long-term memory entry")
    add_lt_parser.add_argument("--content", required=True, help="Memory content")
    add_lt_parser.add_argument("--category", default="general", choices=["physiological_traits", "preferences_and_habits", "coaching_directives", "general"], help="Category")
    add_lt_parser.add_argument("--tags", help="Comma-separated tags")

    add_c_parser = mem_subparsers.add_parser("add-constraint", help="Add calendar constraint")
    add_c_parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    add_c_parser.add_argument("--end", help="End date (YYYY-MM-DD, optional)")
    add_c_parser.add_argument("--description", required=True, help="Constraint description (e.g. University Exam)")
    add_c_parser.add_argument("--type", default="exam", help="Constraint type (exam, holiday, travel, illness, etc.)")
    add_c_parser.add_argument("--action", default="no_training", help="Action (no_training, easy_only, etc.)")
    add_c_parser.add_argument("--sync-intervals", action="store_true", help="Sync to Intervals.icu calendar as HOLIDAY/NOTE")

    add_r_parser = mem_subparsers.add_parser("add-reminder", help="Add follow-up reminder")
    add_r_parser.add_argument("--description", required=True, help="Reminder description (e.g. Ask for workout RPE)")
    add_r_parser.add_argument("--trigger", default="next_interaction", help="Trigger condition")
    add_r_parser.add_argument("--target-date", help="Target date (YYYY-MM-DD)")
    add_r_parser.add_argument("--due-date", help="Due date (YYYY-MM-DD)")
    add_r_parser.add_argument("--priority", choices=["normal", "high"], default="normal", help="Priority")

    comp_r_parser = mem_subparsers.add_parser("complete-reminder", help="Mark follow-up reminder as completed")
    comp_r_parser.add_argument("--id", required=True, help="Reminder ID (e.g. st_r_xxx)")
    comp_r_parser.add_argument("--notes", help="Completion notes")

    add_p_parser = mem_subparsers.add_parser("add-status", help="Add temporary physiological status")
    add_p_parser.add_argument("--description", required=True, help="Status description")
    add_p_parser.add_argument("--severity", choices=["mild", "moderate", "severe"], default="mild", help="Severity")
    add_p_parser.add_argument("--days", type=int, default=3, help="Duration in days")

    # 8. External Calendars
    cal_parser = subparsers.add_parser("calendars", help="Manage and inspect external iCal calendars (Google, UniBo)")
    cal_subparsers = cal_parser.add_subparsers(dest="cal_action", help="Calendar actions")

    cal_subparsers.add_parser("list", help="List configured external calendars")

    cal_sync_parser = cal_subparsers.add_parser("sync", help="Fetch and sync external calendars to athlete memory")
    cal_sync_parser.add_argument("--days", type=int, default=30, help="Days ahead to sync (default: 30)")
    cal_sync_parser.add_argument("--force-refresh", action="store_true", help="Bypass cache and force HTTP fetch")

    cal_sched_parser = cal_subparsers.add_parser("schedule", help="Inspect daily commitments, commute buffers, and training windows")
    cal_sched_parser.add_argument("--date", help="Target date (YYYY-MM-DD, defaults to today)")
    cal_sched_parser.add_argument("--workout-min", type=int, default=45, help="Estimated workout duration in minutes")
    cal_sched_parser.add_argument("--commute-min", type=int, help="Override commute buffer in minutes")
    cal_sched_parser.add_argument("--force-refresh", action="store_true", help="Bypass cache and force HTTP fetch")


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
            "integrations": {
                "intervals_ical_sync": getattr(args, "intervals_ical_sync", False),
                "external_calendar_commitments_sync": getattr(args, "external_calendar_sync", False),
                "device_ecosystem": getattr(args, "device_ecosystem", ""),
            },
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


    elif args.command == "memory":
        mm = MemoryManager()
        if args.mem_action == "list":
            mem = mm.get_memory()
            print(format_json(mem))

        elif args.mem_action == "prompt-context":
            ctx = mm.format_memory_summary_for_prompt()
            print(ctx)

        elif args.mem_action == "prune":
            result = mm.prune_expired_entries()
            print("✅ Pruned expired memory entries:")
            print(format_json(result))

        elif args.mem_action == "sync-calendar":
            s_date = args.start or date.today().strftime("%Y-%m-%d")
            e_date = args.end or (date.today() + timedelta(days=60)).strftime("%Y-%m-%d")
            imported = mm.sync_calendar_constraints_from_intervals(api, s_date, e_date)
            print(f"✅ Synced {len(imported)} calendar constraints from Intervals.icu:")
            print(format_json(imported))


        elif args.mem_action == "add-long-term":
            tags_list = [t.strip() for t in args.tags.split(",")] if args.tags else []
            item = mm.add_long_term_memory(
                content=args.content,
                category=args.category,
                tags=tags_list,
            )
            print("✅ Long-term memory added:")
            print(format_json(item))

        elif args.mem_action == "add-constraint":
            item = mm.add_calendar_constraint(
                date_start=args.start,
                date_end=args.end,
                description=args.description,
                constraint_type=args.type,
                action=args.action,
                sync_intervals=args.sync_intervals,
                intervals_client=api,
            )
            print("✅ Calendar constraint added:")
            print(format_json(item))

        elif args.mem_action == "add-reminder":
            item = mm.add_follow_up_reminder(
                description=args.description,
                trigger_condition=args.trigger,
                target_date=args.target_date,
                priority=args.priority,
                due_date=args.due_date,
            )
            print("✅ Follow-up reminder added:")
            print(format_json(item))

        elif args.mem_action == "complete-reminder":
            success = mm.complete_follow_up(reminder_id=args.id, completion_notes=args.notes)
            if success:
                print(f"✅ Follow-up reminder {args.id} marked as completed.")
            else:
                print(f"❌ Follow-up reminder {args.id} not found.")

        elif args.mem_action == "add-status":
            item = mm.add_temporary_status(
                description=args.description,
                severity=args.severity,
                duration_days=args.days,
            )
            print("✅ Temporary physiological status recorded:")
            print(format_json(item))

        else:
            mem_parser.print_help()

    elif args.command == "calendars":
        ecm = ExternalCalendarManager()
        if args.cal_action == "list":
            sources = ecm.get_calendar_sources()
            print(f"Configured external calendars ({len(sources)}):")
            for s in sources:
                status = "ENABLED" if s.get("enabled", True) else "DISABLED"
                print(f"- [{status}] {s.get('name')} ({s.get('type')})")
                print(f"  URL: {s.get('url')}")
                print(f"  Commute Buffer: {s.get('commute_minutes', 0)} min")

        elif args.cal_action == "sync":
            mm = MemoryManager()
            imported = ecm.sync_to_memory_manager(mm, days_ahead=args.days, force_refresh=args.force_refresh)
            print(f"✅ Synchronized {len(imported)} external calendar events to Coach Memory (next {args.days} days).")

        elif args.cal_action == "schedule":
            target_d = args.date or datetime.now(ecm.tz).date().isoformat()
            sched = ecm.get_daily_schedule(target_d, commute_override_min=args.commute_min, force_refresh=args.force_refresh)
            print(f"📅 Schedule Analysis for {sched['date']}:")
            print(f"🛌 Sleep Routine: Wake-up at {sched.get('wake_up_time', '07:30')} (Bedtime: {sched.get('bedtime', '00:00')}, Routine: {sched.get('routine_applied', 'standard')})")
            if sched["has_all_day_block"]:
                print("⚠️ ALL-DAY COMMITMENT / EXAM DETECTED: Full day blocked for training.")
            print(f"\nEvents ({len(sched['events'])}):")
            if not sched["events"]:
                print("  (No commitments found)")
            for ev in sched["events"]:
                print(f"  • {ev['start']} - {ev['end']} | {ev['summary']} [{ev['calendar']}] ({ev.get('location') or 'No location'})")
            print("\nBusy Blocks (including travel/commute buffers):")
            if not sched["busy_blocks"]:
                print("  (None)")
            for b in sched["busy_blocks"]:
                print(f"  • {b['effective_start']} - {b['effective_end']} ({b['summary']}) [commute: {b['commute_minutes']}m]")
            print("\nFree Training Windows:")
            if not sched["free_windows"]:
                print("  (None available)")
            for w in sched["free_windows"]:
                print(f"  • {w['start']} - {w['end']} ({w['duration_minutes']} min, slot: {w['slot']})")

            slot = ecm.find_optimal_training_slot(target_d, workout_duration_min=args.workout_min)
            if slot:
                print(f"\n🏃 Recommended Training Slot ({args.workout_min}m run + 35m shower/recovery):")
                print(f"  Start: {slot['recommended_start']} ➡️ Finish: {slot['recommended_end']} (Ready by: {slot['post_workout_ready']})")
                print(f"  Safety Margin: +{slot['margin_minutes']} min")
            else:
                print(f"\n⚠️ No viable {args.workout_min}m window found on {target_d} without conflicting with commitments/commute.")
        else:
            cal_parser.print_help()

    else:
        parser.print_help()



if __name__ == "__main__":
    main()

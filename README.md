# 🏃 Autonomous Endurance Coaching Engine for Intervals.icu

[![License: PolyForm Noncommercial](https://img.shields.io/badge/License-PolyForm%20Noncommercial-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Antigravity%20CLI%20%7C%20Claude%20Code%20%7C%20Cursor-orange.svg)](https://github.com/federicoporpora/intervals-icu-coach)
[![Intervals.icu API](https://img.shields.io/badge/API-Intervals.icu-red.svg)](https://intervals.icu)

An autonomous, deterministic, agent-driven coaching system that runs locally via the **Antigravity CLI**, **Claude Code** (`CLAUDE.md`), **Cursor** (`.cursorrules`), or any agentic coding environment, synchronizing with **[Intervals.icu](https://intervals.icu)** via REST API for workout planning, physiological wellness tracking, and activity analysis.


---

## 1. System Architecture

```
coach_engine/
├── config/
│   ├── athlete_profile.json        # Dynamic profile with field-level ISO timestamps
│   ├── athlete_profile.example.json# Template profile example
│   ├── athlete_memory.json         # Dual-horizon long-term traits & short-term memory
│   ├── athlete_memory.example.json # Example memory template
│   ├── staleness_rules.json        # TTL rules for dynamic metrics (days)
│   └── coaching_philosophy.md      # Training principles, zone models, and progression rules
├── tools/
│   ├── __init__.py                 # Tool package exports
│   ├── memory_manager.py           # Dual-horizon memory, constraints & follow-up reminders
│   ├── external_calendar.py        # External iCal reader (Google/UniBo) & schedule solver
│   ├── intervals_api.py            # Deterministic wrapper for Intervals.icu REST API
│   ├── workout_analyzer.py         # Lap/split breakdown, decoupling, and zone compliance
│   ├── plan_generator.py           # Interval workout syntax generator for Intervals.icu
│   └── state_manager.py            # Onboarding check and profile staleness validation
├── data/
│   └── cache/                      # Cached wellness, event, and activity payloads
├── cli.py                          # Terminal interface for testing and inspection
└── agent_instructions.md           # Core runtime prompt for the Antigravity agent
```

---

## 2. Configuration & State Management

### Metric Staleness System (`config/staleness_rules.json`)
Controls maximum Time-To-Live (TTL in days) for key athlete metrics:
```json
{
  "weight_kg": 14,
  "resting_hr_baseline": 30,
  "lthr_bpm": 60,
  "threshold_pace_sec_km": 45,
  "max_hr_bpm": 90,
  "target_events": 30,
  "weekly_availability": 30
}
```

### Dual-Horizon Memory Architecture (`config/athlete_memory.json`)
Persists athlete context across independent chat conversations:
* **Long-Term Memory**: Enduring physiological traits (e.g. tendon sensitivity on high volume), scheduling preferences, and coaching directives (e.g. strict Heart-Rate-First discipline).
* **Short-Term Memory**:
  * **Calendar Constraints**: Date-bounded life constraints (e.g., exams, business trips, holidays) with automated Intervals.icu calendar sync (`HOLIDAY`/`NOTE` markers).
  * **Pending Follow-Ups & Reminders**: Miscellaneous coach reminders requiring future athlete check-ins (e.g., reporting subjective RPE/feeling after a key workout).
  * **Temporary Statuses**: Acute fatigue, illness, or muscle tightness flags with auto-computed expiration.

---

## 3. Tool Reference

### `tools/memory_manager.py`
Dual-horizon athlete memory engine:
* `add_long_term_memory(content, category, tags)`: Saves persistent athlete traits and coaching preferences.
* `get_long_term_memories(category, tag)`: Queries long-term memories.
* `add_calendar_constraint(date_start, date_end, description, type, action, sync_intervals, intervals_client)`: Registers non-training or restricted days and optionally pushes `HOLIDAY`/`NOTE` events to Intervals.icu calendar.
* `is_date_blocked(date_str)`: Deterministically checks if a day is marked as `no_training`.
* `add_follow_up_reminder(description, trigger, priority)`: Logs pending follow-ups (e.g. workout feeling check).
* `get_pending_follow_ups()`: Surfaces pending follow-up items for proactive coaching in the next conversation.
* `complete_follow_up(id, notes)`: Marks reminder completed with timestamp and report summary.
* `prune_expired_entries()`: Cleans expired calendar constraints and temporary status flags.
* `format_memory_summary_for_prompt()`: Generates structured markdown for agent runtime prompt injection.

### `tools/external_calendar.py`
Live external calendar ingestion and training window solver:
* `fetch_feed(url)`: Fetches iCal / webcal feeds (Google Calendar, UniBo lezioni) with intelligent disk caching.
* `parse_ical(content, cal_name, cal_type, default_commute_minutes)`: RFC 5545 unfolding parser normalizing datetimes to athlete timezone (`Europe/Rome`).
* `get_daily_schedule(target_date)`: Calculates busy intervals, applies commute buffers (e.g. 45 min for university lectures), and computes free training windows.
* `find_optimal_training_slot(target_date, workout_duration_min, shower_buffer_min)`: Deterministically identifies the best training slot accommodating the workout and post-workout shower/recovery buffer (e.g. 35 min).
* `sync_to_memory_manager(memory_manager)`: Directly registers life constraints and dynamic lecture busy windows into MemoryManager without touching Intervals.icu (preventing calendar duplicate loops).

### `tools/intervals_api.py`
Deterministic REST API client utilizing HTTP Basic Auth (`API_KEY:<user_api_key>`):
* `get_wellness(start_date, end_date)`: Fetches HRV (rMSSD), resting HR, sleep duration/score, and subjective fatigue/soreness.
* `get_activities(oldest, newest)`: Retrieves list of completed sessions.
* `get_activity_details(activity_id)`: Fetches interval breakdowns, per-kilometer splits, HR streams, cadence, and pace.
* `get_activity_streams(activity_id, types)`: Retrieves high-resolution time-series data.
* `get_events(oldest, newest)`: Retrieves planned calendar workouts.
* `create_planned_workout(event_payload)`: Pushes workouts to Intervals.icu calendar using structured text syntax.
* `create_calendar_holiday(start_date, end_date, name, description)`: Pushes holiday/rest events to calendar.
* `create_calendar_note(date_val, name, description)`: Pushes annotations and calendar notes.
* `delete_planned_workout(event_id)` / `delete_calendar_event(event_id)`: Removes calendar items.

### `tools/workout_analyzer.py`
Exercise physiology and performance math:
* **Aerobic Decoupling ($EF_1 \text{ vs } EF_2$)**: Calculates Efficiency Factor drift across workout halves. Categorizes decoupling rate:
  * $< 3.5\%$: Elite / Excellent aerobic stability
  * $3.5\% - 5.0\%$: Good aerobic conditioning
  * $5.0\% - 7.5\%$: Moderate drift (thermal strain/volume boundary)
  * $> 7.5\%$: Excessive decoupling (fatigue / cardiac drift)
* **Lap & Split Breakdown**: Evaluates kilometer splits, pacing consistency rating ($\sigma_{\text{pace}}$), and negative split execution.
* **Interval Compliance & Fade**: Measures work rep adherence, target vs actual velocity/power, and drop-off percentage across repetitions.
* **Autonomic Recovery Status**: Evaluates daily HRV (rMSSD) deviations, Resting HR shifts, sleep score, and Acute:Chronic Workload Ratio (ACWR) to assign readiness status (`GREEN`, `AMBER`, `RED`).

### `tools/plan_generator.py`
Generates valid Intervals.icu structured workouts:
* **Running & Cycling Templates**: Polarized Base Z2, VO2max Intervals, Lactate Threshold Cruise, Sweet Spot Cycling, Progressive Long Run, and Active Recovery.
* **Dynamic Adaptation Engine**: Deterministically adapts upcoming workouts when `AMBER` or `RED` fatigue flags are triggered.
* **Constraint Filtering**: `filter_available_training_days(dates, memory_manager)` prevents scheduling workouts on blocked calendar days.

### `tools/state_manager.py`
* `is_initialized()`: Cold-start detection.
* `get_stale_metrics()`: Identifies metrics exceeding TTL boundaries.
* `initialize_profile(data)`: Computes custom HR/Pace zones and stamps all fields.
* `update_profile(updates)`: Updates specific metrics and timestamps.

---

## 4. Antigravity Agent Lifecycle Directives

1. **Cold-Start Interceptor**: If `state_manager.is_initialized()` is `False`, the agent intercepts the conversation, halts standard responses, and presents the structured onboarding questionnaire (calibrating physiology, training availability, target races, and calendar synchronization).
2. **Pre-Flight Staleness Check**: Checks `state_manager.get_stale_metrics()` and alerts if parameters need updating.
3. **Pre-Flight Memory & Follow-Up Check**: Automatically checks `memory_manager.get_pending_follow_ups()`. If pending reminders exist (e.g. asking athlete for RPE/feeling from a previous workout), the coach proactively addresses them.
4. **Constraint-Aware Planning**: Prohibits scheduling sessions on dates marked as blocked in `memory_manager.get_active_calendar_constraints()`.
5. **Deterministic Workout Review**: Fetches activity data, computes decoupling, splits, and interval compliance, and delivers actionable coaching feedback.
6. **Adaptive Planning**: Synchronizes directly with Intervals.icu calendar to adjust volume or intensity when under-recovery or life disruptions occur.

---

## 5. Connected Ecosystem & Two-Way Calendar Synergy

The coaching engine provides full two-way calendar synergy and smartwatch synchronization:
* **Outbound Workout Sync (Intervals.icu $\rightarrow$ Google / Apple Calendar)**: Uses the live Intervals.icu iCal feed (*Calendar -> Options -> Export Calendar*, or via `intervals_api.get_calendar_feed_url()`) to mirror workouts and races dynamically into Google Calendar, Apple Calendar, or Outlook.
* **Inbound Life Commitments Sync (Google Calendar / Notes $\rightarrow$ Intervals.icu $\rightarrow$ Coach Engine)**:
  * Connect personal Google Calendar into Intervals.icu via *Calendar -> Options -> Add Calendar* (pasting the private iCal link), or add `NOTE`, `HOLIDAY`, or `SICK` entries directly on the Intervals.icu calendar.
  * The Coach calls `memory_manager.sync_calendar_constraints_from_intervals()` before planning to automatically detect exams, travel, scout camps, and holidays, protecting personal days and shifting key sessions without dropping physiological progression.
* **Smartwatch & Device Sync**: Structured workouts pushed to Intervals.icu automatically sync directly to Garmin Connect, Suunto Guides, Coros, Wahoo, and Apple Watch.

---

## 6. Quickstart & CLI Usage

### Installation & Environment Setup
```bash
git clone https://github.com/federicoporpora/intervals-icu-coach.git
cd intervals-icu-coach

# Install dependencies
pip install -r requirements.txt

# Copy example environment file
cp .env.example .env

# Edit .env with your Intervals.icu API Key and Athlete ID
# INTERVALS_API_KEY=your_api_key_here
# INTERVALS_ATHLETE_ID=0
```

### CLI Commands
```bash
# Check initialization status
python3 -m coach_engine.cli status

# Initialize athlete profile
python3 -m coach_engine.cli init --name "Runner" --weight 68.0 --rhr 48 --max-hr 192 --lthr 174 --threshold-pace-sec 240

# Check for stale metrics
python3 -m coach_engine.cli staleness

# Manage Memory
python3 -m coach_engine.cli memory list
python3 -m coach_engine.cli memory prompt-context
python3 -m coach_engine.cli memory add-constraint --start "2026-09-01" --end "2026-09-01" --description "University Exam" --action "no_training"
python3 -m coach_engine.cli memory add-reminder --description "Ask athlete for RPE on 5x1k VO2max" --priority "high"
python3 -m coach_engine.cli memory complete-reminder --id "st_r_xxxx" --notes "Athlete felt strong"
python3 -m coach_engine.cli memory add-long-term --content "Strict Z2 HR discipline (<154 bpm)" --category "coaching_directives" --tags "hr,zone2"

# Generate structured workout syntax
python3 -m coach_engine.cli generate-workout --type vo2max --reps 5

# Run test suite
python3 -m unittest discover -s tests -v
```

---

## 6. License & Terms

This project is licensed under the **PolyForm Noncommercial License 1.0.0** (Personal & Non-Commercial Use Only) - see the [LICENSE](LICENSE) file for details.

* **Permitted**: Free for individual athletes for personal training analysis, research, and non-commercial educational use.
* **Prohibited**: Any commercial use, SaaS deployment, platform integration, closed redistribution, or monetization without prior written permission from [Federico Porpora](https://github.com/federicoporpora).



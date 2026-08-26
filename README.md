# 🏃 Autonomous Endurance Coaching Engine for Intervals.icu

[![License: PolyForm Noncommercial](https://img.shields.io/badge/License-PolyForm%20Noncommercial-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Antigravity%20CLI-orange.svg)](https://github.com/google)
[![Intervals.icu API](https://img.shields.io/badge/API-Intervals.icu-red.svg)](https://intervals.icu)

An autonomous, deterministic, agent-driven coaching system that runs locally via the **Antigravity CLI** and synchronizes with **[Intervals.icu](https://intervals.icu)** via REST API for workout planning, physiological wellness tracking, and activity analysis.

---

## 1. System Architecture

```
coach_engine/
├── config/
│   ├── athlete_profile.json        # Dynamic profile with field-level ISO timestamps
│   ├── athlete_profile.example.json# Template profile example
│   ├── staleness_rules.json        # TTL rules for dynamic metrics (days)
│   └── coaching_philosophy.md      # Training principles, zone models, and progression rules
├── tools/
│   ├── __init__.py                 # Tool package exports
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

### Athlete Profile Schema (`config/athlete_profile.json`)
Maintains field-level ISO 8601 timestamps (`updated_at`) for every dynamic physiological parameter, 5-zone HR models (based on %LTHR), and 6-zone Running Pace models (relative to Threshold Pace).

---

## 3. Tool Reference

### `tools/intervals_api.py`
Deterministic REST API client utilizing HTTP Basic Auth (`API_KEY:<user_api_key>`):
* `get_wellness(start_date, end_date)`: Fetches HRV (rMSSD), resting HR, sleep duration/score, and subjective fatigue/soreness.
* `get_activities(oldest, newest)`: Retrieves list of completed sessions.
* `get_activity_details(activity_id)`: Fetches interval breakdowns, per-kilometer splits, HR streams, cadence, and pace.
* `get_activity_streams(activity_id, types)`: Retrieves high-resolution time-series data.
* `get_events(oldest, newest)`: Retrieves planned calendar workouts.
* `create_planned_workout(event_payload)`: Pushes workouts to Intervals.icu calendar using structured text syntax.
* `update_planned_workout(event_id, event_payload)`: Reschedules or adapts workouts.

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

### `tools/state_manager.py`
* `is_initialized()`: Cold-start detection.
* `get_stale_metrics()`: Identifies metrics exceeding TTL boundaries.
* `initialize_profile(data)`: Computes custom HR/Pace zones and stamps all fields.
* `update_profile(updates)`: Updates specific metrics and timestamps.

---

## 4. Antigravity Agent Lifecycle Directives

1. **Cold-Start Interceptor**: If `state_manager.is_initialized()` is `False`, the agent intercepts the conversation, halts standard responses, and presents the structured onboarding questionnaire.
2. **Pre-Flight Staleness Check**: Before responding to any prompt, the agent checks `state_manager.get_stale_metrics()` and prepends a reminder if parameters need updating.
3. **Deterministic Workout Review**: Fetches activity data, computes decoupling, splits, and interval compliance, and delivers actionable coaching feedback.
4. **Adaptive Planning**: Synchronizes directly with Intervals.icu calendar to adjust volume or intensity when under-recovery is detected.

---

## 5. Quickstart & CLI Usage

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


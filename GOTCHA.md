# 🛑 COACH ENGINE GOTCHAS & ANTI-PATTERNS (Token-Saving Guide)

> **MANDATORY FOR ALL AI AGENTS & DEVELOPERS:**  
> Read this file before running CLI commands, writing Python scripts, or inspecting repo data.  
> Adhering to these rules prevents hallucinated commands, Python tracebacks, unhandled `None` crashes, schema errors, and thousands of wasted tokens per session.

---

## ⚡ 1. Golden Rules to Avoid Token Waste

1. **Prefer the CLI over inline `python3 -c "..."` scripts**:  
   Almost everything (checking status, staleness, readiness, schedule availability, completing reminders, workout reviews) has a deterministic CLI command. Writing ad-hoc scripts often crashes due to syntax/kwargs errors.
2. **Never dump massive JSONs into conversation context**:  
   - ❌ `python3 -m coach_engine.cli memory list` dumps +150 lines of JSON.
   - ✅ `python3 -m coach_engine.cli memory prompt-context` outputs a concise 25-line markdown summary.
   - ✅ `python3 -m coach_engine.cli memory list-reminders` outputs only pending reminders.
3. **Never guess file paths or schemas**:  
   - Configuration files are located in `coach_engine/config/`, **NEVER** in `coach_engine/data/`.
   - Profile and Memory dictionaries are deeply nested; root-level `.get("field")` will silently return `None`.
4. **Never compare Intervals.icu stream elements without `None` checks**:  
   Intervals.icu streams frequently contain `None` during pauses and GPS dropouts. Direct comparison crashes with `TypeError: '>' not supported between instances of 'NoneType' and 'int'`.
5. **Never write hybrid or composite zone tokens in workouts**:  
   - ❌ `Z1/Z2 HR` or `Z2-Z3 HR` breaks the Intervals.icu parser and generates an uncolored white gap.
   - ✅ Always use a single canonical token: `Z1 HR`, `Z2 HR`, `Z3 HR`, `Z4 HR`, `Z5 HR`.

---

## 💻 2. CLI Subcommands Cheat Sheet (Exact Syntax)

Execute all commands as: `python3 -m coach_engine.cli <command> [subcommand] [flags]`

| Area | Command | Flags / Options | Purpose & Output |
|---|---|---|---|
| **System** | `status` | *(none)* | Checks onboarding status, athlete name, configured HR/Pace zones. |
| **Metrics** | `staleness` | *(none)* | Checks metric TTLs (e.g. `weight_kg` > 14d, `lthr_bpm` > 60d). |
| **Readiness**| `readiness` | `[--days 7]` | Evaluates autonomic readiness, HRV suppression, and RHR drift. |
| **Review** | `review` | `--activity-id <ID> [--use-cache]` | Computes aerobic decoupling, laps, interval compliance, and fatigue flags. |
| **Schedule** | `calendars schedule` | `--date YYYY-MM-DD [--workout-min 45] [--hard] [--force-refresh]` | Solves availability windows, busy blocks with commute buffers, and optimal slots. *(Alias: `calendars show-window`)* |
| **Calendars**| `calendars list` | *(none)* | Lists external iCal sources (Google, UniBo). |
| **Calendars**| `calendars sync` | `[--days 30] [--force-refresh]` | Ingests external calendar commitments into Coach Memory. |
| **Memory** | `memory prompt-context`| *(none)* | **Token-efficient** formatted markdown of traits, active constraints, and follow-ups. |
| **Memory** | `memory list-reminders`| *(none)* | **Compact** list of pending follow-up reminders. |
| **Memory** | `memory complete-reminder`| `--id <ID> [--notes "..."]` | Marks a reminder completed with notes and timestamp. |
| **Memory** | `memory add-reminder` | `--description "..." [--priority normal\|high] [--target-date YYYY-MM-DD]` | Adds a proactive follow-up reminder. |
| **Memory** | `memory add-constraint`| `--start YYYY-MM-DD [--end YYYY-MM-DD] --description "..." [--action no_training] [--sync-intervals]` | Blocks dates (`no_training`) and optionally syncs to Intervals.icu. |
| **Memory** | `memory prune` | *(none)* | Removes expired calendar constraints and temporary statuses. |
| **Memory** | `memory list` | *(none)* | Full memory JSON dump (**Warning: large token payload**). |
| **Workout** | `generate-workout` | `--type easy\|vo2max\|threshold\|long_run\|recovery [--duration 45] [--sport Run]` | Generates structured workout syntax. |

### ❌ Hallucinated CLI Commands to Avoid:
- ❌ `python3 -m coach_engine.cli memory list-reminders` ➡️ (Previously invalid, now aliased, but prefer `prompt-context` or `list-reminders`).
- ❌ `python3 -m coach_engine.cli calendars show-window --date ...` ➡️ (Previously invalid, now aliased to `calendars schedule --date ...`).

---

## 🐍 3. Python Tools Registry & Method Signatures

When writing scripts or interacting directly with `coach_engine/tools/`:

### A. `ExternalCalendarManager`
```python
# ✅ CORRECT IMPORT
from coach_engine.tools.external_calendar import ExternalCalendarManager

# ❌ WRONG: ExternalCalendarSolver does NOT exist!
```
- **Inspect Daily Schedule & Windows**:
  ```python
  ecm = ExternalCalendarManager()
  sched = ecm.get_daily_schedule("2026-10-02")
  # Keys in sched:
  # - sched['events']: [{'summary': ..., 'start': ..., 'end': ..., 'calendar': ...}]
  # - sched['busy_blocks']: [{'summary': ..., 'effective_start': ..., 'effective_end': ..., 'commute_minutes': ...}]
  # - sched['free_windows']: [{'start': ..., 'end': ..., 'duration_minutes': ..., 'slot': ...}]
  # - sched['has_all_day_block']: bool
  ```
- **Find Recommended Training Slot**:
  ```python
  slot = ecm.find_optimal_training_slot("2026-10-02", workout_duration_min=45, is_hard_workout=False)
  # Keys in slot (if slot is not None):
  # - slot['recommended_start']: e.g. "17:10"
  # - slot['recommended_end']: e.g. "17:55"
  # - slot['post_workout_ready']: e.g. "18:30"
  # - slot['margin_minutes']: e.g. 210
  # - slot['meal_advice']: e.g. "..."
  # ❌ NOTE: slot does NOT contain 'commitments' or 'events'! Look in sched['events'].
  # ❌ WRONG METHOD NAME: ecm.find_daily_training_slot() does NOT exist! Use find_optimal_training_slot().
  ```

---

## B. `MemoryManager`
```python
from coach_engine.tools.memory_manager import MemoryManager
mm = MemoryManager()
```
- **Complete Follow-up Reminder**:
  ```python
  # ✅ Parameter is `completion_notes` (alias `notes` also supported):
  mm.complete_follow_up("st_r_5e06f684", completion_notes="Atleta conferma riposo.")
  # Or simply via CLI:
  # python3 -m coach_engine.cli memory complete-reminder --id st_r_5e06f684 --notes "..."
  ```
- **Inspect Active Constraints & Follow-ups**:
  ```python
  pending = mm.get_pending_follow_ups()  # Returns list of pending reminder dicts
  constraints = mm.get_active_calendar_constraints()  # Returns list of active constraints
  ```
- **Add / Remove Calendar Constraints**:
  ```python
  mm.add_calendar_constraint(
      date_start="2026-10-03",
      date_end="2026-10-04",
      description="Weekend fuori porta",
      constraint_type="personal",
      action="no_training",
      sync_intervals=True,
      intervals_client=api
  )
  mm.remove_calendar_constraint("st_c_bc435aff")
  ```

---

## C. `IntervalsAPIClient`
```python
from coach_engine.tools.intervals_api import get_intervals_client, IntervalsAPIClient

api = get_intervals_client()  # Uses singleton factory loading credentials from .env
```
- **Activities**:
  - `acts = api.get_activities(oldest_iso_date, newest_iso_date)`
  - `det = api.get_activity_details(activity_id, use_cache=True)`
  - `streams = api.get_activity_streams(activity_id, types=['distance', 'time', 'heartrate', 'altitude', 'velocity_smooth'])`
- **Calendar & Planned Workouts**:
  - `events = api.get_events(oldest_iso_date, newest_iso_date)`
  - `ev = api.get_event(event_id)`
  - `res = api.create_planned_workout(payload)`
  - `res = api.update_planned_workout(event_id, payload)`
  - `res = api.delete_planned_workout(event_id)`  *(or `api.delete_calendar_event(event_id)`)*
  - `res = api.create_calendar_holiday(start_date, end_date, name, description)`
  - `res = api.create_calendar_note(date_val, name, description, category="NOTE")`

---

## 📁 4. Correct File Paths

| File | Correct Path | ❌ Common Mistake (DO NOT USE) |
|---|---|---|
| Athlete Profile | `coach_engine/config/athlete_profile.json` | ❌ `coach_engine/data/athlete_profile.json` |
| Athlete Memory | `coach_engine/config/athlete_memory.json` | ❌ `coach_engine/data/athlete_memory.json` |
| Staleness Rules | `coach_engine/config/staleness_rules.json` | ❌ `coach_engine/data/staleness_rules.json` |
| Coaching Philosophy | `coach_engine/config/coaching_philosophy.md`| ❌ `coach_engine/coaching_philosophy.md` |
| Cache Storage | `coach_engine/data/cache/` | *(Only cache files live under `data/`)* |

> ⚠️ Running `find coach_engine/ -type f` dumps +120 lines of output into chat. Check this table instead!

---

## 🗺️ 5. JSON Schemas & Access Patterns

### A. Athlete Profile (`athlete_profile.json`)
The profile is strictly categorized into namespaces:
```json
{
  "initialized": true,
  "personal": {
    "name": "Athlete Name",
    "weight_kg": { "value": 68.0, "updated_at": "..." }
  },
  "metrics": {
    "lthr_bpm": { "value": 188, "updated_at": "..." },
    "max_hr_bpm": { "value": 204, "updated_at": "..." },
    "resting_hr_baseline": { "value": 46, "updated_at": "..." },
    "threshold_pace_sec_km": { "value": 265.0, "updated_at": "..." },
    "hr_zones": [ ... ],
    "pace_zones": [ ... ]
  },
  "preferences": {
    "coaching_philosophy": "Polarized 80/20",
    "strengths": [ ... ],
    "weaknesses": [ ... ]
  },
  "target_events": [ ... ]
}
```
- ❌ **WRONG**:
  `prof.get("target_races")` ➡️ returns `None` (key is `target_events`)  
  `prof.get("coaching_philosophy")` ➡️ returns `None` (nested in `preferences`)  
  `prof.get("lthr_zones_hr")` ➡️ returns `None` (nested in `metrics["hr_zones"]`)  
  `prof.get("pace_zones")` ➡️ returns `None` (nested in `metrics["pace_zones"]`)
- ✅ **CORRECT**:
  `prof.get("preferences", {}).get("coaching_philosophy")`  
  `prof.get("metrics", {}).get("hr_zones", [])`  
  `prof.get("target_events", [])`

---

### B. Athlete Memory (`athlete_memory.json`)
```json
{
  "version": "1.0",
  "updated_at": "...",
  "long_term": {
    "physiological_traits": [ ... ],
    "preferences_and_habits": [ ... ],
    "coaching_directives": [ ... ],
    "general": [ ... ]
  },
  "short_term": {
    "calendar_constraints": [ ... ],
    "follow_ups_and_reminders": [ ... ],
    "temporary_physiological_status": [ ... ]
  }
}
```
- ❌ **WRONG**:
  `mem.get("short_term_context")` ➡️ returns `None` (key is `short_term`)  
  `mem.get("calendar_constraints")` ➡️ returns `None` (nested in `short_term`)
- ✅ **CORRECT**:
  `mem.get("short_term", {}).get("calendar_constraints", [])`  
  `mem.get("short_term", {}).get("follow_ups_and_reminders", [])`  
  Or simply use helper methods: `mm.get_active_calendar_constraints()` and `mm.get_pending_follow_ups()`.

---

## 🌊 6. Intervals.icu Streams: Mandatory `None` Handling

When retrieving streams via `client.get_activity_streams(act_id, types=[...])`:
Arrays like `dist`, `time_s`, `hr`, and `alt` can and do contain `None` values (e.g., watch paused, GPS search, chest strap disconnect).

❌ **CRASHES WITH `TypeError`**:
```python
if dist[i] >= current_km * 1000:  # Crashes if dist[i] is None!
    km_time = time_s[i] - time_s[start_idx]
```

✅ **SAFE FILTERING**:
```python
stream_dict = {s['type']: s['data'] for s in streams}
dist = stream_dict.get('distance', [])
time_s = stream_dict.get('time', [])
hr = stream_dict.get('heartrate', [])
alt = stream_dict.get('altitude', [])

for i in range(len(dist)):
    d = dist[i]
    if d is not None and d >= current_km * 1000:
        km_time = (time_s[i] or 0) - (time_s[start_idx] or 0)
        valid_hrs = [h for h in hr[start_idx:i+1] if h is not None]
        km_hr = sum(valid_hrs) / len(valid_hrs) if valid_hrs else 0
        ...
```

---

## 🏃 7. Intervals.icu Workout Syntax & Watch Compatibility

1. **`m` means MINUTES, never meters**:
   - `15m` = 15 minutes.
   - For distance, ALWAYS use `km`: `1km`, `0.4km`, `1.5km`, `10km`.
2. **Step Text Labels MUST be at the BEGINNING of the line**:
   - ✅ `- Riscaldamento graduale 1.5km Z1 HR 5:50-6:10 min/km`
   - ❌ `- 1.5km Z1 HR 5:50-6:10 min/km Riscaldamento graduale`
   - *Why*: Intervals.icu only populates `step.text` (which Suunto Guides and Garmin displays show) when the text is at the start.
3. **Single Canonical Zone Token Only**:
   - ✅ `Z2 HR` or `Z1 HR`
   - ❌ `Z1/Z2 HR` or `Z2-Z3 HR` (regex fails, leaving a blank white gap in the chart).
4. **Cooldown / Commute Transition**:
   - Always include appropriate Z1 cooldown distance (e.g. at least 1.0 km) to account for returning home or post-workout transition.

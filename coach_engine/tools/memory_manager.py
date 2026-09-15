"""
Deterministic Dual-Horizon Memory Manager
=========================================
Manages persistent long-term athlete traits, preferences, and coaching directives,
alongside short-term calendar constraints (with Intervals.icu sync), pending
follow-up reminders, and temporary physiological statuses.
"""

import os
import json
import uuid
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union


class MemoryManager:
    """Deterministic manager for athlete dual-horizon memory (long-term & short-term)."""

    def __init__(self, memory_path: Optional[Union[str, Path]] = None):
        base_dir = Path(__file__).resolve().parent.parent
        self.memory_path = Path(memory_path) if memory_path else base_dir / "config" / "athlete_memory.json"

    @staticmethod
    def current_iso_timestamp() -> str:
        """Returns current UTC ISO 8601 timestamp."""
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _parse_timestamp(ts_str: Optional[str]) -> Optional[datetime]:
        """Parses ISO 8601 string or date string into a timezone-aware UTC datetime."""
        if not ts_str or not isinstance(ts_str, str) or not ts_str.strip():
            return None
        try:
            clean_ts = ts_str.replace("Z", "+00:00")
            if len(clean_ts) == 10 and clean_ts.count("-") == 2:
                # Date string YYYY-MM-DD
                dt = datetime.strptime(clean_ts, "%Y-%m-%d")
                return dt.replace(tzinfo=timezone.utc)
            dt = datetime.fromisoformat(clean_ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None

    def _default_memory_structure(self) -> Dict[str, Any]:
        """Returns the default initial empty memory structure."""
        return {
            "version": "1.0",
            "updated_at": self.current_iso_timestamp(),
            "long_term": {
                "physiological_traits": [],
                "preferences_and_habits": [],
                "coaching_directives": [],
                "general": [],
            },
            "short_term": {
                "calendar_constraints": [],
                "follow_ups_and_reminders": [],
                "temporary_physiological_status": [],
            },
        }

    def get_memory(self) -> Dict[str, Any]:
        """Loads and returns the memory JSON. Creates default file if missing."""
        if not self.memory_path.exists():
            default_mem = self._default_memory_structure()
            self.save_memory(default_mem)
            return default_mem
        try:
            with open(self.memory_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Ensure structure integrity
                data.setdefault("long_term", {})
                data.setdefault("short_term", {})
                data["long_term"].setdefault("physiological_traits", [])
                data["long_term"].setdefault("preferences_and_habits", [])
                data["long_term"].setdefault("coaching_directives", [])
                data["long_term"].setdefault("general", [])
                data["short_term"].setdefault("calendar_constraints", [])
                data["short_term"].setdefault("follow_ups_and_reminders", [])
                data["short_term"].setdefault("temporary_physiological_status", [])
                return data
        except Exception:
            default_mem = self._default_memory_structure()
            self.save_memory(default_mem)
            return default_mem

    def save_memory(self, memory_data: Dict[str, Any]) -> None:
        """Saves memory data to disk with an updated timestamp."""
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        memory_data["updated_at"] = self.current_iso_timestamp()
        with open(self.memory_path, "w", encoding="utf-8") as f:
            json.dump(memory_data, f, indent=2)

    # --------------------------------------------------------------------------
    # 1. Long-Term Memory
    # --------------------------------------------------------------------------
    def add_long_term_memory(
        self,
        content: str,
        category: str = "general",
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Adds a persistent long-term fact, physiological trait, preference, or directive.
        Categories: 'physiological_traits', 'preferences_and_habits', 'coaching_directives', 'general'.
        """
        memory = self.get_memory()
        now_iso = self.current_iso_timestamp()
        memory_id = f"lt_{uuid.uuid4().hex[:8]}"

        item = {
            "id": memory_id,
            "content": content.strip(),
            "category": category,
            "tags": [t.strip().lower() for t in (tags or []) if t and t.strip()],
            "created_at": now_iso,
            "updated_at": now_iso,
        }

        lt_dict = memory.setdefault("long_term", {})
        if category in lt_dict and isinstance(lt_dict[category], list):
            lt_dict[category].append(item)
        else:
            lt_dict.setdefault("general", []).append(item)

        self.save_memory(memory)
        return item

    def get_long_term_memories(
        self,
        category: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieves long-term memories with optional category and tag filtering."""
        memory = self.get_memory()
        lt = memory.get("long_term", {})
        all_items: List[Dict[str, Any]] = []

        if category and category in lt:
            all_items.extend(lt[category])
        else:
            for cat_list in lt.values():
                if isinstance(cat_list, list):
                    all_items.extend(cat_list)

        if tag:
            target_tag = tag.strip().lower()
            all_items = [
                item for item in all_items
                if target_tag in [t.lower() for t in item.get("tags", [])]
            ]

        return all_items

    def update_long_term_memory(
        self,
        memory_id: str,
        content: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Updates an existing long-term memory item."""
        memory = self.get_memory()
        lt = memory.get("long_term", {})
        target_item = None
        target_cat = None

        for cat_name, cat_list in lt.items():
            if isinstance(cat_list, list):
                for item in cat_list:
                    if item.get("id") == memory_id:
                        target_item = item
                        target_cat = cat_name
                        break
            if target_item:
                break

        if not target_item:
            return None

        if content is not None:
            target_item["content"] = content.strip()
        if tags is not None:
            target_item["tags"] = [t.strip().lower() for t in tags if t and t.strip()]
        target_item["updated_at"] = self.current_iso_timestamp()

        # If category changed and differs from current bucket
        if category and category != target_cat:
            lt[target_cat].remove(target_item)
            target_item["category"] = category
            if category in lt and isinstance(lt[category], list):
                lt[category].append(target_item)
            else:
                lt.setdefault("general", []).append(target_item)

        self.save_memory(memory)
        return target_item

    def delete_long_term_memory(self, memory_id: str) -> bool:
        """Deletes a long-term memory item by ID."""
        memory = self.get_memory()
        lt = memory.get("long_term", {})
        deleted = False

        for cat_list in lt.values():
            if isinstance(cat_list, list):
                for item in list(cat_list):
                    if item.get("id") == memory_id:
                        cat_list.remove(item)
                        deleted = True
                        break

        if deleted:
            self.save_memory(memory)
        return deleted

    def sync_calendar_constraints_from_intervals(
        self,
        intervals_client: Any,
        start_date: Union[str, date, datetime],
        end_date: Union[str, date, datetime],
    ) -> List[Dict[str, Any]]:
        """
        Fetches all calendar events from Intervals.icu in the specified range,
        detects non-workout items (NOTE, HOLIDAY, SICK, INJURED, external calendar imports),
        and records active calendar constraints in local short-term memory.
        """
        oldest_str = start_date.strftime("%Y-%m-%d") if isinstance(start_date, (date, datetime)) else str(start_date).split("T")[0]
        newest_str = end_date.strftime("%Y-%m-%d") if isinstance(end_date, (date, datetime)) else str(end_date).split("T")[0]

        raw_events = intervals_client.get_events(oldest=oldest_str, newest=newest_str)
        if not raw_events or not isinstance(raw_events, list):
            return []

        imported_constraints: List[Dict[str, Any]] = []
        memory = self.get_memory()
        st_constraints = memory.setdefault("short_term", {}).setdefault("calendar_constraints", [])

        # Keywords that indicate heavy commitments or non-training days
        blocking_keywords = [
            "esame", "exam", "laurea", "viaggio", "travel", "volo", "flight",
            "uscita", "campo", "camp", "scout", "no training", "no corsa", "giornata piena",
            "cerimonia", "matrimonio", "festa", "controlli automatici"
        ]

        for ev in raw_events:
            cat = str(ev.get("category", "")).upper()
            if cat == "WORKOUT" or cat.startswith("RACE_"):
                continue

            ev_id = str(ev.get("id", ""))
            start_local = str(ev.get("start_date_local", ""))
            end_local = str(ev.get("end_date_local", ""))
            name = ev.get("name") or "Note / Event"
            description = ev.get("description") or ""

            start_d = start_local[:10] if len(start_local) >= 10 else oldest_str
            end_d = end_local[:10] if len(end_local) >= 10 else start_d

            # Handle midnight boundary for all-day notes
            if end_local.endswith("T00:00:00") and end_d > start_d:
                try:
                    s_dt = datetime.strptime(start_d, "%Y-%m-%d")
                    e_dt = datetime.strptime(end_d, "%Y-%m-%d")
                    if (e_dt - s_dt).days == 1:
                        end_d = start_d
                    else:
                        end_d = (e_dt - timedelta(days=1)).strftime("%Y-%m-%d")
                except Exception:
                    pass

            text_corpus = f"{name} {description}".lower()
            is_blocking = cat in ["HOLIDAY", "SICK", "INJURED"] or any(kw in text_corpus for kw in blocking_keywords)
            action = "no_training" if is_blocking else "available"
            c_type = "holiday" if cat == "HOLIDAY" else ("illness" if cat in ["SICK", "INJURED"] else "commitment")

            # Check if constraint already exists
            existing = None
            for c in st_constraints:
                if c.get("intervals_event_id") == ev_id:
                    existing = c
                    break

            now_iso = self.current_iso_timestamp()
            desc_str = f"{name}: {description}".strip(": ") if description else name

            if existing:
                existing["date_start"] = start_d
                existing["date_end"] = end_d
                existing["description"] = desc_str
                existing["action"] = action
                existing["type"] = c_type
                existing["expires_at"] = f"{end_d}T23:59:59Z"
                existing["updated_at"] = now_iso
                imported_constraints.append(existing)
            else:
                new_c = {
                    "id": f"st_c_{uuid.uuid4().hex[:8]}",
                    "date_start": start_d,
                    "date_end": end_d,
                    "type": c_type,
                    "description": desc_str,
                    "action": action,
                    "synced_to_intervals": True,
                    "intervals_event_id": ev_id,
                    "created_at": now_iso,
                    "expires_at": f"{end_d}T23:59:59Z",
                }
                st_constraints.append(new_c)
                imported_constraints.append(new_c)

        self.save_memory(memory)
        return imported_constraints

    def sync_calendar_constraints_from_external_feeds(
        self,
        external_manager: Optional[Any] = None,
        days_ahead: int = 30,
        force_refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Fetches events from external iCal feeds (Google Calendar, UniBo lezioni)
        and synchronizes them directly into local memory as calendar constraints.
        """
        if external_manager is None:
            from .external_calendar import ExternalCalendarManager
            external_manager = ExternalCalendarManager()
        return external_manager.sync_to_memory_manager(self, days_ahead=days_ahead, force_refresh=force_refresh)


    # --------------------------------------------------------------------------
    # 2. Short-Term Memory: Calendar Constraints
    # --------------------------------------------------------------------------
    def add_calendar_constraint(
        self,
        date_start: str,
        date_end: Optional[str] = None,
        description: str = "",
        constraint_type: str = "exam",
        action: str = "no_training",
        sync_intervals: bool = False,
        intervals_client: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Adds a short-term calendar constraint (e.g. exam, holiday, travel, illness).
        Optionally syncs directly with Intervals.icu calendar as a HOLIDAY or NOTE event.
        """
        memory = self.get_memory()
        now_iso = self.current_iso_timestamp()
        constraint_id = f"st_c_{uuid.uuid4().hex[:8]}"
        
        end_d = date_end if date_end and date_end.strip() else date_start
        # Expiration at 23:59:59 UTC on end_date
        expires_at = f"{end_d}T23:59:59Z"

        item: Dict[str, Any] = {
            "id": constraint_id,
            "date_start": date_start.strip(),
            "date_end": end_d.strip(),
            "type": constraint_type.strip().lower(),
            "description": description.strip(),
            "action": action.strip().lower(),
            "synced_to_intervals": False,
            "intervals_event_id": None,
            "created_at": now_iso,
            "expires_at": expires_at,
        }

        # Optional sync with Intervals.icu
        if sync_intervals and intervals_client:
            try:
                event_name = f"Constraint: {constraint_type.capitalize()} ({description[:30]})"
                resp = intervals_client.create_calendar_holiday(
                    start_date=date_start,
                    end_date=end_d,
                    name=event_name,
                    description=description or f"Calendar constraint: {constraint_type}",
                )
                if resp and isinstance(resp, dict) and "id" in resp:
                    item["synced_to_intervals"] = True
                    item["intervals_event_id"] = str(resp["id"])
            except Exception:
                # If sync fails (e.g., offline/no API key), preserve local constraint
                item["synced_to_intervals"] = False

        st_constraints = memory.setdefault("short_term", {}).setdefault("calendar_constraints", [])
        st_constraints.append(item)
        self.save_memory(memory)
        return item

    def get_active_calendar_constraints(
        self,
        for_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        as_of_date: Optional[Union[str, datetime]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieves active calendar constraints.
        Can filter by a specific target date or date range.
        Excludes constraints whose expires_at is before as_of_date.
        """
        memory = self.get_memory()
        constraints = memory.get("short_term", {}).get("calendar_constraints", [])
        
        now_dt = (
            self._parse_timestamp(as_of_date)
            if isinstance(as_of_date, str)
            else as_of_date or datetime.now(timezone.utc)
        )

        active: List[Dict[str, Any]] = []
        for c in constraints:
            exp_dt = self._parse_timestamp(c.get("expires_at"))
            if exp_dt and exp_dt < now_dt:
                continue

            c_start = c.get("date_start", "")
            c_end = c.get("date_end", c_start)

            if for_date:
                if c_start <= for_date <= c_end:
                    active.append(c)
            elif start_date and end_date:
                # Overlap check: max(c_start, start_date) <= min(c_end, end_date)
                if max(c_start, start_date) <= min(c_end, end_date):
                    active.append(c)
            else:
                active.append(c)

        return active

    def is_date_blocked(self, date_str: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Checks if a specific date (YYYY-MM-DD) is blocked for training.
        Returns (is_blocked: bool, constraint_dict or None).
        """
        constraints = self.get_active_calendar_constraints(for_date=date_str)
        for c in constraints:
            if c.get("action") == "no_training":
                return True, c
        return False, None

    def remove_calendar_constraint(
        self,
        constraint_id: str,
        delete_from_intervals: bool = True,
        intervals_client: Optional[Any] = None,
    ) -> bool:
        """Removes a calendar constraint by ID and optionally deletes from Intervals.icu."""
        memory = self.get_memory()
        constraints = memory.get("short_term", {}).get("calendar_constraints", [])
        target = None

        for c in list(constraints):
            if c.get("id") == constraint_id:
                target = c
                constraints.remove(c)
                break

        if not target:
            return False

        if delete_from_intervals and target.get("intervals_event_id") and intervals_client:
            try:
                intervals_client.delete_calendar_event(target["intervals_event_id"])
            except Exception:
                pass

        self.save_memory(memory)
        return True

    # --------------------------------------------------------------------------
    # 3. Short-Term Memory: Follow-ups and Reminders
    # --------------------------------------------------------------------------
    def add_follow_up_reminder(
        self,
        description: str,
        trigger_condition: str = "next_interaction",
        target_date: Optional[str] = None,
        priority: str = "normal",
        due_date: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Adds a pending follow-up reminder / miscellaneous task.
        Example: Coach asks athlete to report workout feeling/RPE on the next chat.
        """
        memory = self.get_memory()
        now_iso = self.current_iso_timestamp()
        reminder_id = f"st_r_{uuid.uuid4().hex[:8]}"

        item: Dict[str, Any] = {
            "id": reminder_id,
            "description": description.strip(),
            "trigger_condition": trigger_condition.strip(),
            "target_date": target_date.strip() if target_date else None,
            "due_date": due_date.strip() if due_date else None,
            "priority": priority.strip().lower(),
            "status": "pending",
            "metadata": metadata or {},
            "created_at": now_iso,
            "completed_at": None,
            "completion_notes": None,
        }

        reminders = memory.setdefault("short_term", {}).setdefault("follow_ups_and_reminders", [])
        reminders.append(item)
        self.save_memory(memory)
        return item

    def get_pending_follow_ups(
        self,
        as_of_date: Optional[Union[str, datetime]] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieves all pending follow-up reminders that need coach attention."""
        memory = self.get_memory()
        reminders = memory.get("short_term", {}).get("follow_ups_and_reminders", [])
        
        pending: List[Dict[str, Any]] = []
        for r in reminders:
            if r.get("status") == "pending":
                pending.append(r)

        # Sort high priority first, then by creation date
        pending.sort(key=lambda x: (0 if x.get("priority") == "high" else 1, x.get("created_at", "")))
        return pending

    def complete_follow_up(
        self,
        reminder_id: str,
        completion_notes: Optional[str] = None,
    ) -> bool:
        """Marks a follow-up reminder as completed with timestamp and notes."""
        memory = self.get_memory()
        reminders = memory.get("short_term", {}).get("follow_ups_and_reminders", [])
        found = False

        for r in reminders:
            if r.get("id") == reminder_id:
                r["status"] = "completed"
                r["completed_at"] = self.current_iso_timestamp()
                r["completion_notes"] = completion_notes.strip() if completion_notes else None
                found = True
                break

        if found:
            self.save_memory(memory)
        return found

    def dismiss_follow_up(self, reminder_id: str) -> bool:
        """Dismisses a follow-up reminder without completion."""
        memory = self.get_memory()
        reminders = memory.get("short_term", {}).get("follow_ups_and_reminders", [])
        found = False

        for r in reminders:
            if r.get("id") == reminder_id:
                r["status"] = "dismissed"
                r["completed_at"] = self.current_iso_timestamp()
                found = True
                break

        if found:
            self.save_memory(memory)
        return found

    # --------------------------------------------------------------------------
    # 4. Short-Term Memory: Temporary Physiological Status
    # --------------------------------------------------------------------------
    def add_temporary_status(
        self,
        description: str,
        severity: str = "mild",
        duration_days: int = 3,
        date_recorded: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Records temporary fatigue, soreness, minor pain, or sickness.
        Auto-computes expiration based on duration_days.
        """
        memory = self.get_memory()
        now_iso = self.current_iso_timestamp()
        status_id = f"st_p_{uuid.uuid4().hex[:8]}"

        rec_date_str = date_recorded or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rec_dt = self._parse_timestamp(rec_date_str) or datetime.now(timezone.utc)
        exp_dt = rec_dt + timedelta(days=duration_days)
        expires_at = exp_dt.strftime("%Y-%m-%dT23:59:59Z")

        item = {
            "id": status_id,
            "description": description.strip(),
            "severity": severity.strip().lower(),
            "date_recorded": rec_date_str,
            "duration_days": duration_days,
            "expires_at": expires_at,
            "created_at": now_iso,
        }

        statuses = memory.setdefault("short_term", {}).setdefault("temporary_physiological_status", [])
        statuses.append(item)
        self.save_memory(memory)
        return item

    def get_active_temporary_statuses(
        self,
        as_of_date: Optional[Union[str, datetime]] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieves active temporary physiological status entries."""
        memory = self.get_memory()
        statuses = memory.get("short_term", {}).get("temporary_physiological_status", [])
        
        now_dt = (
            self._parse_timestamp(as_of_date)
            if isinstance(as_of_date, str)
            else as_of_date or datetime.now(timezone.utc)
        )

        active: List[Dict[str, Any]] = []
        for s in statuses:
            exp_dt = self._parse_timestamp(s.get("expires_at"))
            if exp_dt and exp_dt < now_dt:
                continue
            active.append(s)

        return active

    # --------------------------------------------------------------------------
    # 5. Pruning & Maintenance
    # --------------------------------------------------------------------------
    def prune_expired_entries(
        self,
        as_of_date: Optional[Union[str, datetime]] = None,
    ) -> Dict[str, int]:
        """
        Prunes expired short-term calendar constraints and temporary physiological statuses.
        Completed reminders older than 14 days are also cleaned up.
        """
        memory = self.get_memory()
        now_dt = (
            self._parse_timestamp(as_of_date)
            if isinstance(as_of_date, str)
            else as_of_date or datetime.now(timezone.utc)
        )

        st = memory.get("short_term", {})
        
        # 1. Constraints
        orig_c_count = len(st.get("calendar_constraints", []))
        st["calendar_constraints"] = [
            c for c in st.get("calendar_constraints", [])
            if self._parse_timestamp(c.get("expires_at")) is None
            or self._parse_timestamp(c.get("expires_at")) >= now_dt
        ]
        pruned_c = orig_c_count - len(st["calendar_constraints"])

        # 2. Temporary statuses
        orig_s_count = len(st.get("temporary_physiological_status", []))
        st["temporary_physiological_status"] = [
            s for s in st.get("temporary_physiological_status", [])
            if self._parse_timestamp(s.get("expires_at")) is None
            or self._parse_timestamp(s.get("expires_at")) >= now_dt
        ]
        pruned_s = orig_s_count - len(st["temporary_physiological_status"])

        # 3. Old completed reminders (> 14 days after completion)
        fourteen_days_ago = now_dt - timedelta(days=14)
        orig_r_count = len(st.get("follow_ups_and_reminders", []))
        st["follow_ups_and_reminders"] = [
            r for r in st.get("follow_ups_and_reminders", [])
            if r.get("status") == "pending"
            or self._parse_timestamp(r.get("completed_at")) is None
            or self._parse_timestamp(r.get("completed_at")) >= fourteen_days_ago
        ]
        pruned_r = orig_r_count - len(st["follow_ups_and_reminders"])

        if pruned_c > 0 or pruned_s > 0 or pruned_r > 0:
            self.save_memory(memory)

        return {
            "pruned_constraints": pruned_c,
            "pruned_statuses": pruned_s,
            "pruned_reminders": pruned_r,
        }

    # --------------------------------------------------------------------------
    # 6. Prompt Context Generator
    # --------------------------------------------------------------------------
    def format_memory_summary_for_prompt(
        self,
        as_of_date: Optional[Union[str, datetime]] = None,
    ) -> str:
        """
        Generates a concise, structured markdown section formatted specifically
        for the coach agent runtime prompt to ensure complete contextual awareness.
        """
        pending_reminders = self.get_pending_follow_ups(as_of_date)
        active_constraints = self.get_active_calendar_constraints(as_of_date=as_of_date)
        active_statuses = self.get_active_temporary_statuses(as_of_date=as_of_date)
        long_term_memories = self.get_long_term_memories()

        lines = ["### 🧠 Coach Active Memory Context"]

        # Reminders
        if pending_reminders:
            lines.append("\n**⚠️ PENDING FOLLOW-UPS & REMINDERS (PROACTIVELY ADDRESS IN THIS TURN):**")
            for r in pending_reminders:
                p_tag = f" [Priority: {r['priority'].upper()}]" if r.get("priority") == "high" else ""
                lines.append(f"- `[ID: {r['id']}]` {r['description']}{p_tag}")
        else:
            lines.append("\n*No pending follow-up reminders.*")

        # Constraints
        if active_constraints:
            lines.append("\n**📅 ACTIVE SHORT-TERM CALENDAR CONSTRAINTS:**")
            for c in active_constraints:
                sync_tag = " (Synced to Intervals.icu)" if c.get("synced_to_intervals") else ""
                lines.append(
                    f"- `{c['date_start']}` to `{c['date_end']}`: {c['description']} "
                    f"[Action: {c['action'].upper()}]{sync_tag}"
                )
        else:
            lines.append("\n*No active calendar constraints.*")

        # Temporary Statuses
        if active_statuses:
            lines.append("\n**🩹 TEMPORARY PHYSIOLOGICAL STATUS:**")
            for s in active_statuses:
                lines.append(
                    f"- {s['description']} (Severity: {s['severity'].upper()}, Recorded: {s['date_recorded']})"
                )

        # Long-Term
        if long_term_memories:
            lines.append("\n**🌟 LONG-TERM ATHLETE TRAITS & DIRECTIVES:**")
            for m in long_term_memories:
                tags_str = f" #{', #'.join(m['tags'])}" if m.get("tags") else ""
                lines.append(f"- `[{m['category']}]` {m['content']}{tags_str}")

        return "\n".join(lines)


# Singleton factory
def get_memory_manager(memory_path: Optional[Union[str, Path]] = None) -> MemoryManager:
    return MemoryManager(memory_path=memory_path)

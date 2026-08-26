"""
Intervals.icu REST API Deterministic Client
===========================================
Wrapper for the Intervals.icu REST API using HTTP Basic Authentication.
Authentication format: ('API_KEY', api_key) with Athlete ID ('0' or 'iXXXXX').
"""

import os
import json
import hashlib
from typing import Dict, Any, List, Optional, Union
from datetime import datetime, date
from pathlib import Path
import requests
from requests.auth import HTTPBasicAuth


class IntervalsAPIError(Exception):
    """Custom exception for Intervals.icu API errors."""
    pass


class IntervalsAPIClient:
    """Deterministic client for Intervals.icu REST API."""

    BASE_URL = "https://intervals.icu/api/v1"

    def __init__(
        self,
        api_key: Optional[str] = None,
        athlete_id: Optional[str] = None,
        cache_dir: Optional[Union[str, Path]] = None,
    ):
        base_dir = Path(__file__).resolve().parent.parent.parent
        env_file = base_dir / ".env"
        env_vars = {}
        if env_file.exists():
            try:
                with open(env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            env_vars[k.strip()] = v.strip().strip('"').strip("'")
            except Exception:
                pass

        # Allow passing explicitly or loading from environment variables / .env
        self.api_key = api_key or os.environ.get("INTERVALS_API_KEY") or env_vars.get("INTERVALS_API_KEY", "")
        self.athlete_id = athlete_id or os.environ.get("INTERVALS_ATHLETE_ID") or env_vars.get("INTERVALS_ATHLETE_ID", "0")
        
        # Setup cache directory
        if cache_dir is None:
            self.cache_dir = Path(__file__).resolve().parent.parent / "data" / "cache"
        else:
            self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def auth(self) -> HTTPBasicAuth:
        """Intervals.icu uses HTTP Basic Auth with username 'API_KEY' and password being the user's API Key."""
        return HTTPBasicAuth("API_KEY", self.api_key)

    @property
    def is_authenticated(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def _get_cache_path(self, cache_key: str) -> Path:
        sanitized = "".join(c if c.isalnum() or c in "-_." else "_" for c in cache_key)
        return self.cache_dir / f"{sanitized}.json"

    def _read_cache(self, cache_key: str) -> Optional[Any]:
        cache_file = self._get_cache_path(cache_key)
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None
        return None

    def _write_cache(self, cache_key: str, data: Any) -> None:
        cache_file = self._get_cache_path(cache_key)
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            # Cache failure should not break live execution
            pass

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        use_cache: bool = False,
        cache_key: Optional[str] = None,
    ) -> Any:
        """Executes an HTTP request with caching, timeout, and deterministic error parsing."""
        if use_cache and cache_key:
            cached_data = self._read_cache(cache_key)
            if cached_data is not None:
                return cached_data

        if not self.is_authenticated:
            # If offline or unauthenticated and cached data exists, return it
            if cache_key:
                cached_data = self._read_cache(cache_key)
                if cached_data is not None:
                    return cached_data
            raise IntervalsAPIError(
                "INTERVALS_API_KEY is not set. Please provide a valid API key or set the environment variable."
            )

        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        headers = {"Content-Type": "application/json"}

        try:
            response = requests.request(
                method=method,
                url=url,
                auth=self.auth,
                params=params,
                json=json_data,
                headers=headers,
                timeout=20,
            )

            if response.status_code >= 400:
                error_msg = f"HTTP {response.status_code}: {response.text}"
                raise IntervalsAPIError(error_msg)

            if response.status_code == 204:
                return None

            data = response.json() if response.content else {}

            if cache_key:
                self._write_cache(cache_key, data)

            return data

        except requests.exceptions.RequestException as e:
            # If request fails but cache exists, attempt fallback
            if cache_key:
                cached_data = self._read_cache(cache_key)
                if cached_data is not None:
                    return cached_data
            raise IntervalsAPIError(f"Network error communicating with Intervals.icu: {str(e)}")

    # --------------------------------------------------------------------------
    # 1. Wellness API
    # --------------------------------------------------------------------------
    def get_wellness(
        self,
        start_date: Union[str, date, datetime],
        end_date: Union[str, date, datetime],
        athlete_id: Optional[str] = None,
        use_cache: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Fetches wellness data (HRV/rMSSD, resting HR, sleep duration/score, fatigue, soreness, etc.)
        between start_date and end_date (inclusive, YYYY-MM-DD format).
        """
        aid = athlete_id or self.athlete_id
        start_str = start_date.strftime("%Y-%m-%d") if isinstance(start_date, (date, datetime)) else str(start_date)
        end_str = end_date.strftime("%Y-%m-%d") if isinstance(end_date, (date, datetime)) else str(end_date)
        
        cache_key = f"wellness_{aid}_{start_str}_{end_str}"
        endpoint = f"athlete/{aid}/wellness"
        params = {"oldest": start_str, "newest": end_str}

        result = self._request("GET", endpoint, params=params, use_cache=use_cache, cache_key=cache_key)
        return result if isinstance(result, list) else [result] if result else []

    # --------------------------------------------------------------------------
    # 2. Activities API
    # --------------------------------------------------------------------------
    def get_activities(
        self,
        oldest: Union[str, date, datetime],
        newest: Union[str, date, datetime],
        athlete_id: Optional[str] = None,
        use_cache: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Retrieves summary list of completed activities in the date range.
        Dates in YYYY-MM-DD format.
        """
        aid = athlete_id or self.athlete_id
        oldest_str = oldest.strftime("%Y-%m-%d") if isinstance(oldest, (date, datetime)) else str(oldest)
        newest_str = newest.strftime("%Y-%m-%d") if isinstance(newest, (date, datetime)) else str(newest)

        cache_key = f"activities_{aid}_{oldest_str}_{newest_str}"
        endpoint = f"athlete/{aid}/activities"
        params = {"oldest": oldest_str, "newest": newest_str}

        result = self._request("GET", endpoint, params=params, use_cache=use_cache, cache_key=cache_key)
        return result if isinstance(result, list) else []

    def get_activity_details(
        self,
        activity_id: Union[str, int],
        use_cache: bool = False,
    ) -> Dict[str, Any]:
        """
        Fetches detailed activity data including intervals (icu_intervals / icu_groups),
        laps, pace/power curves, and per-km breakdowns.
        """
        act_id = str(activity_id)
        cache_key = f"activity_{act_id}_details"
        endpoint = f"activity/{act_id}"

        result = self._request("GET", endpoint, use_cache=use_cache, cache_key=cache_key)
        return result or {}

    def get_activity_streams(
        self,
        activity_id: Union[str, int],
        types: Optional[List[str]] = None,
        use_cache: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Fetches raw time-series streams for the activity (heartrate, velocity_smooth, watts, cadence, altitude, etc.).
        """
        act_id = str(activity_id)
        types_str = "_".join(sorted(types)) if types else "all"
        cache_key = f"activity_{act_id}_streams_{types_str}"
        endpoint = f"activity/{act_id}/streams"
        params = {"types": ",".join(types)} if types else None

        result = self._request("GET", endpoint, params=params, use_cache=use_cache, cache_key=cache_key)
        return result or []

    # --------------------------------------------------------------------------
    # 3. Calendar & Planned Workout API
    # --------------------------------------------------------------------------
    def get_events(
        self,
        oldest: Union[str, date, datetime],
        newest: Union[str, date, datetime],
        athlete_id: Optional[str] = None,
        use_cache: bool = False,
    ) -> List[Dict[str, Any]]:
        """Retrieves planned calendar events / workouts in the date window."""
        aid = athlete_id or self.athlete_id
        oldest_str = oldest.strftime("%Y-%m-%d") if isinstance(oldest, (date, datetime)) else str(oldest)
        newest_str = newest.strftime("%Y-%m-%d") if isinstance(newest, (date, datetime)) else str(newest)

        cache_key = f"events_{aid}_{oldest_str}_{newest_str}"
        endpoint = f"athlete/{aid}/events"
        params = {"oldest": oldest_str, "newest": newest_str}

        result = self._request("GET", endpoint, params=params, use_cache=use_cache, cache_key=cache_key)
        return result if isinstance(result, list) else []

    def get_event(
        self,
        event_id: Union[str, int],
        athlete_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetches a specific planned event by ID."""
        aid = athlete_id or self.athlete_id
        endpoint = f"athlete/{aid}/events/{event_id}"
        return self._request("GET", endpoint)

    def create_planned_workout(
        self,
        event_payload: Dict[str, Any],
        athlete_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Pushes a planned workout to the Intervals.icu calendar.
        
        Required payload keys typically include:
          - category: "WORKOUT"
          - start_date_local: "YYYY-MM-DDTHH:MM:SS" (or "YYYY-MM-DDT00:00:00")
          - type: "Run" | "Ride" | "Swim" | "Row" | "Walk" | "Other"
          - name: "5x1k VO2max"
          - description: Structured text workout steps, e.g.:
              "- 15m 65% HR Warmup\n- 5x 1000m 95% PACE / 2m 60% HR\n- 10m 65% HR Cool"
        """
        aid = athlete_id or self.athlete_id
        endpoint = f"athlete/{aid}/events"
        
        # Ensure category is WORKOUT if not set
        if "category" not in event_payload:
            event_payload["category"] = "WORKOUT"

        return self._request("POST", endpoint, json_data=event_payload)

    def update_planned_workout(
        self,
        event_id: Union[str, int],
        event_payload: Dict[str, Any],
        athlete_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Updates or reschedules an existing planned workout."""
        aid = athlete_id or self.athlete_id
        endpoint = f"athlete/{aid}/events/{event_id}"
        return self._request("PUT", endpoint, json_data=event_payload)

    def delete_planned_workout(
        self,
        event_id: Union[str, int],
        athlete_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Deletes a planned workout from the calendar."""
        aid = athlete_id or self.athlete_id
        endpoint = f"athlete/{aid}/events/{event_id}"
        return self._request("DELETE", endpoint)


# Default singleton factory
def get_intervals_client(api_key: Optional[str] = None, athlete_id: Optional[str] = None) -> IntervalsAPIClient:
    return IntervalsAPIClient(api_key=api_key, athlete_id=athlete_id)

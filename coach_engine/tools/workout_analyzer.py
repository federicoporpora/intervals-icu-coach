"""
Deterministic Workout and Physiological Analyzer
=================================================
Performs mathematical analysis of endurance activities and wellness streams:
- Aerobic decoupling (Pw:HR and Pa:HR drift)
- Lap/split pace consistency and pacing variability
- Target vs actual interval compliance and execution fade
- Autonomic recovery status and Acute:Chronic Workload Ratio (ACWR)
"""

from typing import Dict, Any, List, Optional, Tuple, Union
import math
import statistics
from datetime import datetime, date


def sec_to_pace_str(seconds_per_km: float) -> str:
    """Converts seconds/km to MM:SS/km string format."""
    if not seconds_per_km or math.isnan(seconds_per_km) or seconds_per_km <= 0 or seconds_per_km > 3600:
        return "--:--"
    m = int(seconds_per_km // 60)
    s = int(round(seconds_per_km % 60))
    if s == 60:
        m += 1
        s = 0
    return f"{m}:{s:02d}/km"


def speed_to_pace_sec(speed_mps: float) -> float:
    """Converts speed in m/s to pace in sec/km."""
    if not speed_mps or speed_mps <= 0.1:
        return 0.0
    return 1000.0 / speed_mps


def compute_aerobic_decoupling(
    activity_details: Dict[str, Any],
    streams: Optional[Dict[str, List[Union[float, int]]]] = None,
) -> Dict[str, Any]:
    """
    Computes aerobic decoupling (cardiac drift) across the 1st and 2nd halves of steady work.
    
    Formula:
      Efficiency Factor (EF) = Speed (m/s) / HR (bpm)  [Running]
                           or Normalized Power (W) / HR (bpm) [Cycling]
      Decoupling % = ((EF_first_half - EF_second_half) / EF_first_half) * 100
    
    Returns structured analysis with diagnostic assessment.
    """
    sport_type = activity_details.get("type", "Run")
    is_cycling = sport_type in ["Ride", "VirtualRide", "GravelRide", "MountainBike"]

    # 1. Prefer stream-based high-resolution computation if available
    if streams and "heartrate" in streams and ("velocity_smooth" in streams or "watts" in streams):
        hr_stream = streams.get("heartrate", [])
        speed_stream = streams.get("velocity_smooth", [])
        watts_stream = streams.get("watts", [])

        n = min(len(hr_stream), len(speed_stream) if not is_cycling else len(watts_stream))
        if n > 120:  # At least 2 minutes of stream data
            midpoint = n // 2
            
            # First half
            h1_hr = [hr_stream[i] for i in range(midpoint) if hr_stream[i] and hr_stream[i] > 40]
            # Second half
            h2_hr = [hr_stream[i] for i in range(midpoint, n) if hr_stream[i] and hr_stream[i] > 40]

            if is_cycling and watts_stream:
                h1_power = [watts_stream[i] for i in range(midpoint) if watts_stream[i] is not None]
                h2_power = [watts_stream[i] for i in range(midpoint, n) if watts_stream[i] is not None]
                
                avg_h1_hr = statistics.mean(h1_hr) if h1_hr else 0
                avg_h2_hr = statistics.mean(h2_hr) if h2_hr else 0
                avg_h1_power = statistics.mean(h1_power) if h1_power else 0
                avg_h2_power = statistics.mean(h2_power) if h2_power else 0

                ef1 = avg_h1_power / avg_h1_hr if avg_h1_hr > 0 else 0
                ef2 = avg_h2_power / avg_h2_hr if avg_h2_hr > 0 else 0
                metric_name = "Power:HR (W/bpm)"
            else:
                h1_speed = [speed_stream[i] for i in range(midpoint) if speed_stream[i] and speed_stream[i] > 0.5]
                h2_speed = [speed_stream[i] for i in range(midpoint, n) if speed_stream[i] and speed_stream[i] > 0.5]
                
                avg_h1_hr = statistics.mean(h1_hr) if h1_hr else 0
                avg_h2_hr = statistics.mean(h2_hr) if h2_hr else 0
                avg_h1_speed = statistics.mean(h1_speed) if h1_speed else 0
                avg_h2_speed = statistics.mean(h2_speed) if h2_speed else 0

                ef1 = avg_h1_speed / avg_h1_hr if avg_h1_hr > 0 else 0
                ef2 = avg_h2_speed / avg_h2_hr if avg_h2_hr > 0 else 0
                metric_name = "Pace:HR (m/s/bpm)"

            if ef1 > 0:
                decoupling_pct = round(((ef1 - ef2) / ef1) * 100.0, 2)
                return _evaluate_decoupling(decoupling_pct, ef1, ef2, metric_name, avg_h1_hr, avg_h2_hr)

    # 2. Intervals.icu native decoupling metric fallback if available
    icu_decoupling = activity_details.get("icu_efficiency_factor_decoupling") or activity_details.get("decoupling")
    if icu_decoupling is not None:
        dec_val = round(float(icu_decoupling), 2)
        return _evaluate_decoupling(dec_val, 0.0, 0.0, "Intervals.icu native decoupling", 0, 0)

    # 3. Lap-based computation fallback
    laps = activity_details.get("icu_intervals") or activity_details.get("laps") or []
    if len(laps) >= 2:
        valid_laps = [
            l for l in laps 
            if (l.get("moving_time") or l.get("elapsed_time", 0)) > 60 and (l.get("average_heartrate") or 0) > 40
        ]
        if len(valid_laps) >= 2:
            mid = len(valid_laps) // 2
            first_half = valid_laps[:mid]
            second_half = valid_laps[mid:]

            def get_half_ef(lap_list: List[Dict[str, Any]]) -> Tuple[float, float]:
                tot_dist = sum(l.get("distance", 0) for l in lap_list)
                tot_time = sum(l.get("moving_time") or l.get("elapsed_time", 1) for l in lap_list)
                weighted_hr = sum((l.get("average_heartrate", 0)) * (l.get("moving_time") or 1) for l in lap_list)
                avg_hr = weighted_hr / tot_time if tot_time > 0 else 0
                avg_speed = tot_dist / tot_time if tot_time > 0 else 0
                ef = (avg_speed / avg_hr) if avg_hr > 0 else 0
                return ef, avg_hr

            ef1, hr1 = get_half_ef(first_half)
            ef2, hr2 = get_half_ef(second_half)
            if ef1 > 0:
                decoupling_pct = round(((ef1 - ef2) / ef1) * 100.0, 2)
                return _evaluate_decoupling(decoupling_pct, ef1, ef2, "Lap Pace:HR", hr1, hr2)

    return {
        "decoupling_pct": None,
        "classification": "INSUFFICIENT_DATA",
        "ef_first_half": 0.0,
        "ef_second_half": 0.0,
        "assessment": "Insufficient heart rate or duration data to compute aerobic decoupling."
    }


def _evaluate_decoupling(
    decoupling_pct: float,
    ef1: float,
    ef2: float,
    metric_name: str,
    hr1: float,
    hr2: float,
) -> Dict[str, Any]:
    """Applies physiological thresholds to decoupling percentage."""
    if decoupling_pct < 3.5:
        classification = "EXCELLENT"
        assessment = (
            f"Superb aerobic conditioning (Decoupling: {decoupling_pct}%). "
            "Heart rate remained completely stable relative to output throughout the workout. Aerobic foundation is robust."
        )
    elif 3.5 <= decoupling_pct <= 5.0:
        classification = "GOOD"
        assessment = (
            f"Optimal aerobic stability (Decoupling: {decoupling_pct}%). "
            "Cardiovascular drift is well within acceptable physiological limits (< 5.0%)."
        )
    elif 5.0 < decoupling_pct <= 7.5:
        classification = "MODERATE_DRIFT"
        assessment = (
            f"Mild aerobic decoupling observed (Decoupling: {decoupling_pct}%). "
            "Slight cardiac drift indicates thermal strain, dehydration, or reaching the threshold of current endurance duration."
        )
    else:
        classification = "EXCESSIVE_DECOUPLING"
        assessment = (
            f"Significant aerobic decoupling (Decoupling: {decoupling_pct}%). "
            "Substantial cardiac drift (> 7.5%) detected. Indicates fatigue, glycogen depletion, or that this duration exceeds current aerobic capacity."
        )

    return {
        "decoupling_pct": decoupling_pct,
        "classification": classification,
        "metric": metric_name,
        "ef_first_half": round(ef1, 4),
        "ef_second_half": round(ef2, 4),
        "hr_first_half": round(hr1, 1),
        "hr_second_half": round(hr2, 1),
        "assessment": assessment,
    }


def analyze_lap_splits(activity_details: Dict[str, Any]) -> Dict[str, Any]:
    """
    Breaks down lap / kilometer splits, calculating pacing consistency,
    split standard deviation, and negative split execution.
    """
    raw_laps = activity_details.get("icu_intervals") or activity_details.get("laps") or []
    
    splits = []
    paces_sec = []
    hrs = []
    powers = []
    cadences = []

    for idx, lap in enumerate(raw_laps, 1):
        dist_m = lap.get("distance", 0)
        time_s = lap.get("moving_time") or lap.get("elapsed_time", 0)
        if time_s <= 5 or dist_m <= 10:
            continue

        speed_mps = dist_m / time_s if time_s > 0 else 0
        pace_sec = speed_to_pace_sec(speed_mps)
        avg_hr = lap.get("average_heartrate") or lap.get("avg_hr") or 0
        avg_power = lap.get("average_watts") or lap.get("avg_watts") or 0
        avg_cadence = lap.get("average_cadence") or lap.get("avg_cadence") or 0

        paces_sec.append(pace_sec)
        if avg_hr:
            hrs.append(avg_hr)
        if avg_power:
            powers.append(avg_power)
        if avg_cadence:
            cadences.append(avg_cadence)

        splits.append({
            "split_num": idx,
            "label": lap.get("label") or lap.get("name") or f"Split {idx}",
            "distance_km": round(dist_m / 1000.0, 2),
            "duration_sec": time_s,
            "pace_sec_km": round(pace_sec, 1),
            "pace_formatted": sec_to_pace_str(pace_sec),
            "avg_hr": round(avg_hr, 1) if avg_hr else None,
            "avg_power_w": round(avg_power, 1) if avg_power else None,
            "avg_cadence": round(avg_cadence, 1) if avg_cadence else None,
        })

    if not paces_sec:
        return {
            "total_splits": 0,
            "splits": [],
            "pace_std_dev_sec": 0.0,
            "pacing_consistency_score": "N/A",
            "is_negative_split": False,
        }

    pace_std_dev = round(statistics.stdev(paces_sec), 2) if len(paces_sec) > 1 else 0.0
    
    # Negative split test: compare first half average pace to second half average pace
    is_neg_split = False
    half_pt = len(paces_sec) // 2
    if half_pt >= 1:
        first_half_pace = statistics.mean(paces_sec[:half_pt])
        second_half_pace = statistics.mean(paces_sec[half_pt:])
        # Faster pace = fewer seconds per km
        is_neg_split = second_half_pace < first_half_pace

    # Pacing score rating based on variance
    if pace_std_dev < 4.0:
        consistency_rating = "METRONOMIC"
    elif pace_std_dev < 8.0:
        consistency_rating = "HIGHLY_CONSISTENT"
    elif pace_std_dev < 15.0:
        consistency_rating = "MODERATELY_VARIABLE"
    else:
        consistency_rating = "HIGH_VARIANCE"

    return {
        "total_splits": len(splits),
        "splits": splits,
        "average_pace_formatted": sec_to_pace_str(statistics.mean(paces_sec)),
        "pace_std_dev_sec": pace_std_dev,
        "pacing_consistency_score": consistency_rating,
        "is_negative_split": is_neg_split,
        "average_hr": round(statistics.mean(hrs), 1) if hrs else None,
        "average_cadence": round(statistics.mean(cadences), 1) if cadences else None,
    }


def analyze_interval_compliance(
    activity_details: Dict[str, Any],
    planned_workout_spec: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Evaluates completed interval reps against target intensities, target durations,
    and detects pacing decay / interval fade.
    """
    raw_intervals = activity_details.get("icu_intervals", [])
    
    # Filter work intervals (Intervals.icu marks interval types or we filter based on intensity)
    work_reps = []
    recovery_reps = []

    for item in raw_intervals:
        itype = item.get("type", "WORK")
        if itype == "WORK" or item.get("intensity", 0) > 80:
            dist = item.get("distance", 0)
            time_s = item.get("moving_time") or item.get("elapsed_time", 0)
            speed = dist / time_s if time_s > 0 else 0
            pace_s = speed_to_pace_sec(speed)
            
            work_reps.append({
                "id": item.get("id"),
                "duration_sec": time_s,
                "distance_m": round(dist, 1),
                "pace_sec_km": round(pace_s, 1),
                "pace_str": sec_to_pace_str(pace_s),
                "avg_hr": item.get("average_heartrate"),
                "max_hr": item.get("max_heartrate"),
                "avg_watts": item.get("average_watts"),
                "target_pace_sec": planned_workout_spec.get("target_pace_sec_km") if planned_workout_spec else None,
                "target_power_w": planned_workout_spec.get("target_power_w") if planned_workout_spec else None,
            })
        else:
            recovery_reps.append(item)

    if not work_reps:
        return {
            "work_intervals_count": 0,
            "work_reps": [],
            "fade_percentage": 0.0,
            "compliance_verdict": "NO_STRUCTURED_INTERVALS_DETECTED",
        }

    # Calculate execution fade: compare first rep(s) vs final rep(s)
    fade_pct = 0.0
    if len(work_reps) >= 2:
        first_rep = work_reps[0]
        last_rep = work_reps[-1]
        
        if first_rep.get("avg_watts") and last_rep.get("avg_watts"):
            # Cycling power fade
            w1 = first_rep["avg_watts"]
            w_last = last_rep["avg_watts"]
            fade_pct = round(((w1 - w_last) / w1) * 100.0, 2) if w1 > 0 else 0.0
        elif first_rep["pace_sec_km"] > 0 and last_rep["pace_sec_km"] > 0:
            # Running pace fade (slower last rep = higher sec/km)
            p1 = first_rep["pace_sec_km"]
            p_last = last_rep["pace_sec_km"]
            fade_pct = round(((p_last - p1) / p1) * 100.0, 2)

    # Compliance classification
    if abs(fade_pct) <= 3.0:
        verdict = "PERFECT_EXECUTION"
        fade_note = "Pacing was exceptionally even across all interval repetitions."
    elif fade_pct > 3.0 and fade_pct <= 7.0:
        verdict = "MINOR_FADE"
        fade_note = f"Minor drop-off in final intervals ({fade_pct}% fade). Energy distribution was slightly aggressive early."
    elif fade_pct > 7.0:
        verdict = "SEVERE_FADE"
        fade_note = f"Significant drop-off in final intervals ({fade_pct}% fade). Athlete went out too fast and accumulated acute metabolic acidosis."
    else:
        verdict = "STRONG_NEGATIVE_SPLIT"
        fade_note = f"Intervals progressed faster towards the end ({abs(fade_pct)}% negative split)."

    return {
        "work_intervals_count": len(work_reps),
        "work_reps": work_reps,
        "fade_percentage": fade_pct,
        "compliance_verdict": verdict,
        "fade_evaluation": fade_note,
    }


def detect_fatigue_and_recovery_status(
    wellness_records: List[Dict[str, Any]],
    athlete_baseline: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Evaluates autonomic recovery and systemic fatigue markers:
    - HRV (rMSSD) trend vs baseline
    - Resting Heart Rate deviation
    - Sleep duration and score
    - Acute:Chronic Workload Ratio (ACWR / ATL / CTL / TSB)
    - Returns readiness status: GREEN | AMBER | RED
    """
    if not wellness_records:
        return {
            "status": "UNKNOWN",
            "readiness_score": 50,
            "hrv_status": "NO_DATA",
            "resting_hr_delta": 0,
            "flags": ["No wellness data available for date range."],
            "recommendation": "Maintain scheduled training unless feeling symptoms of systemic fatigue.",
        }

    # Sort wellness records chronologically
    sorted_wellness = sorted(wellness_records, key=lambda x: x.get("id", ""))
    today = sorted_wellness[-1]

    # Baseline calculations
    hrv_values = [w.get("hrv") or w.get("hrv_sdnn") for w in sorted_wellness if (w.get("hrv") or w.get("hrv_sdnn"))]
    rhr_values = [w.get("restingHR") for w in sorted_wellness if w.get("restingHR")]

    today_hrv = today.get("hrv") or today.get("hrv_sdnn")
    today_rhr = today.get("restingHR")
    today_sleep_s = today.get("sleepSecs", 0) or 0
    today_sleep_hours = round(today_sleep_s / 3600.0, 1)
    today_sleep_score = today.get("sleepScore")
    fatigue_score = today.get("fatigue") or 0  # 1-10
    soreness_score = today.get("soreness") or 0  # 1-10
    
    # Fitness & Fatigue metrics from Intervals.icu
    ctl = today.get("ctl") or 0.0  # Chronic Training Load (Fitness)
    atl = today.get("atl") or 0.0  # Acute Training Load (Fatigue)
    tsb = today.get("tsb") or (ctl - atl)  # Training Stress Balance (Form)
    acwr = round(atl / ctl, 2) if ctl > 5.0 else 1.0

    flags = []
    score = 100

    # 1. HRV evaluation
    baseline_hrv = statistics.mean(hrv_values[:-1]) if len(hrv_values) > 3 else (
        athlete_baseline.get("hrv_baseline") if athlete_baseline else None
    )
    hrv_status = "NORMAL"
    if today_hrv and baseline_hrv:
        hrv_diff_pct = ((today_hrv - baseline_hrv) / baseline_hrv) * 100.0
        if hrv_diff_pct < -15.0:
            hrv_status = "SUPPRESSED"
            score -= 30
            flags.append(f"HRV significantly suppressed ({round(hrv_diff_pct, 1)}% below rolling baseline). Parasympathetic withdrawal.")
        elif hrv_diff_pct > 25.0 and fatigue_score >= 6:
            hrv_status = "PARASYMPATHETIC_SATURATION"
            score -= 20
            flags.append("Elevated HRV accompanied by elevated fatigue (potential parasympathetic saturation/deep overreaching).")

    # 2. Resting HR evaluation
    baseline_rhr = athlete_baseline.get("resting_hr_baseline", {}).get("value") if athlete_baseline else None
    if not baseline_rhr and len(rhr_values) > 3:
        baseline_rhr = statistics.mean(rhr_values[:-1])

    rhr_delta = 0
    if today_rhr and baseline_rhr:
        rhr_delta = round(today_rhr - baseline_rhr, 1)
        if rhr_delta >= 5.0:
            score -= 30
            flags.append(f"Resting HR elevated by +{rhr_delta} bpm above baseline. Sympathetic stress / possible infection or under-recovery.")
        elif rhr_delta >= 3.0:
            score -= 15
            flags.append(f"Resting HR mildly elevated (+{rhr_delta} bpm).")

    # 3. Sleep evaluation
    if today_sleep_hours > 0 and today_sleep_hours < 6.0:
        score -= 20
        flags.append(f"Inadequate sleep duration ({today_sleep_hours} hrs). Impaired glycogen replenishment and tissue repair.")
    if today_sleep_score and today_sleep_score < 60:
        score -= 15
        flags.append(f"Sub-optimal sleep quality score ({today_sleep_score}/100).")

    # 4. Subjective markers
    if soreness_score >= 7:
        score -= 15
        flags.append(f"High subjective muscle soreness ({soreness_score}/10).")
    if fatigue_score >= 7:
        score -= 15
        flags.append(f"High subjective systemic fatigue ({fatigue_score}/10).")

    # 5. ACWR workload safety check
    if acwr > 1.45:
        score -= 20
        flags.append(f"Acute:Chronic Workload Ratio in danger zone ({acwr} > 1.45). High risk of non-functional overreaching.")

    # Final readiness classification
    score = max(0, min(100, score))
    if score >= 75:
        status = "GREEN"
        recommendation = "Full physiological readiness. Proceed with scheduled high-intensity or threshold workout."
    elif 50 <= score < 75:
        status = "AMBER"
        recommendation = "Moderate systemic fatigue detected. Proceed with caution: reduce interval volume by 15-20% or cap intensity at Zone 2."
    else:
        status = "RED"
        recommendation = "High autonomic strain / under-recovery. Do NOT execute high-intensity sessions today. Convert to Active Recovery (Zone 1) or complete rest."

    return {
        "status": status,
        "readiness_score": score,
        "hrv_today": today_hrv,
        "hrv_baseline": round(baseline_hrv, 1) if baseline_hrv else None,
        "hrv_status": hrv_status,
        "resting_hr_today": today_rhr,
        "resting_hr_delta": rhr_delta,
        "sleep_hours": today_sleep_hours,
        "sleep_score": today_sleep_score,
        "ctl_fitness": round(ctl, 1),
        "atl_fatigue": round(atl, 1),
        "tsb_form": round(tsb, 1),
        "acwr": acwr,
        "flags": flags,
        "recommendation": recommendation,
    }


def generate_workout_review_report(
    activity_details: Dict[str, Any],
    wellness_records: Optional[List[Dict[str, Any]]] = None,
    planned_workout: Optional[Dict[str, Any]] = None,
    athlete_baseline: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Synthesizes complete post-workout diagnostic report combining
    interval compliance, decoupling, lap pacing, and physiological readiness.
    """
    decoupling = compute_aerobic_decoupling(activity_details)
    splits = analyze_lap_splits(activity_details)
    intervals = analyze_interval_compliance(activity_details, planned_workout)
    readiness = detect_fatigue_and_recovery_status(wellness_records or [], athlete_baseline)

    name = activity_details.get("name", "Workout")
    sport = activity_details.get("type", "Activity")
    distance_km = round((activity_details.get("distance", 0)) / 1000.0, 2)
    moving_time_s = activity_details.get("moving_time", 0)
    elapsed_time_s = activity_details.get("elapsed_time", 0)
    avg_hr = activity_details.get("average_heartrate")
    max_hr = activity_details.get("max_heartrate")
    icu_load = activity_details.get("icu_training_load") or activity_details.get("training_load", 0)
    
    speed_mps = (distance_km * 1000.0) / moving_time_s if moving_time_s > 0 else 0
    avg_pace_str = sec_to_pace_str(speed_to_pace_sec(speed_mps))

    duration_m = moving_time_s // 60
    duration_rem_s = moving_time_s % 60
    duration_str = f"{duration_m}m {duration_rem_s}s"

    # Actionable coaching insights
    coaching_bullets = []
    
    # Aerobic base feedback
    if decoupling.get("decoupling_pct") is not None:
        coaching_bullets.append(f"**Aerobic Decoupling**: {decoupling['decoupling_pct']}% ({decoupling['classification']}) - {decoupling['assessment']}")
    
    # Pacing feedback
    if splits.get("pacing_consistency_score") != "N/A":
        coaching_bullets.append(
            f"**Pacing Consistency**: {splits['pacing_consistency_score']} (σ = {splits['pace_std_dev_sec']}s/km). "
            + ("Executed a negative split (2nd half faster)." if splits['is_negative_split'] else "Even/positive split pacing.")
        )

    # Interval execution feedback
    if intervals.get("work_intervals_count", 0) > 0:
        coaching_bullets.append(f"**Interval Compliance**: {intervals['compliance_verdict']} - {intervals['fade_evaluation']}")

    # Recovery / Strain warning
    if readiness.get("status") in ["AMBER", "RED"]:
        coaching_bullets.append(f"**Physiological Strain Warning**: {readiness['recommendation']}")

    return {
        "summary": {
            "name": name,
            "sport": sport,
            "distance_km": distance_km,
            "duration": duration_str,
            "average_pace": avg_pace_str,
            "average_hr": avg_hr,
            "max_hr": max_hr,
            "training_load_tss": icu_load,
        },
        "decoupling": decoupling,
        "splits": splits,
        "intervals": intervals,
        "readiness": readiness,
        "coaching_insights": coaching_bullets,
    }

"""
CampusNexus - Disruption Repair Engine
Repairs college timetable after unexpected changes (faculty leave, room breakdown,
added sessions) with:
- ZERO hard constraint violations
- Minimal churn (maximum schedule stability)
- Clear diff of what changed and why
"""

import copy
from backend.app.engines.timetable_solver import solve_timetable

def apply_disruption(data, disruption):
    """Applies disruption changes to the data dictionary following validator rules."""
    d = copy.deepcopy(data)
    fac = {f["id"]: f for f in d["faculty"]}
    for ch in disruption.get("changes", []):
        t = ch["type"]
        if t == "faculty_unavailable":
            for day in ch["days"]:
                fac[ch["faculty_id"]]["unavailable"].append({
                    "day": day,
                    "periods": ch["periods"],
                    "reason": ch.get("reason", "")
                })
        elif t == "room_unavailable":
            for day in ch["days"]:
                d["room_unavailability"].append({
                    "room_id": ch["room_id"],
                    "day": day,
                    "periods": ch["periods"],
                    "reason": ch.get("reason", "")
                })
        elif t == "add_faculty":
            d["faculty"].append(ch["faculty"])
            fac[ch["faculty"]["id"]] = ch["faculty"]
        elif t == "add_session":
            d["sessions"].append(ch["session"])
        elif t == "remove_session":
            d["sessions"] = [s for s in d["sessions"] if s["id"] != ch["session_id"]]
        else:
            raise ValueError(f"Unknown change type: {t}")
    return d

def repair_timetable(data, baseline_schedule, disruption, max_seconds=30.0):
    """
    Repairs timetable after disruption while maximizing schedule stability.
    
    Args:
        data (dict): Original CIT dataset.
        baseline_schedule (dict): The original schedule.json.
        disruption (dict): Disruption json object.
        
    Returns:
        dict: {
            "schedule": dict (complete schedule_after),
            "diff": list of changes,
            "stats": dict (sessions_moved, time_changed, room_only_changed)
        }
    """
    disrupted_data = apply_disruption(data, disruption)

    # Pin baseline sessions
    baseline_sessions = {s["session_id"]: (s["day"], s["start_period"], s["room_id"]) for s in baseline_schedule["sessions"]}

    # Solve with pinned baseline bias
    res = solve_timetable(disrupted_data, pinned_sessions=baseline_sessions, max_seconds=max_seconds)
    if res["status"] not in ("OPTIMAL", "FEASIBLE"):
        return {
            "status": "FAILED",
            "error": "Could not repair timetable without hard violations."
        }

    repaired_sessions = res["sessions"]
    repaired_map = {s["session_id"]: (s["day"], s["start_period"], s["room_id"]) for s in repaired_sessions}

    # Compute diff and stability
    diff = []
    moved = []
    time_changed = 0
    room_only_changed = 0

    # Added sessions
    for sid, cur in repaired_map.items():
        if sid not in baseline_sessions:
            diff.append({
                "session_id": sid,
                "type": "added",
                "to": {"day": cur[0], "start_period": cur[1], "room_id": cur[2]},
                "reason": "Newly added session in disruption"
            })
            continue

        prev = baseline_sessions[sid]
        if cur != prev:
            moved.append(sid)
            is_time = (cur[0] != prev[0] or cur[1] != prev[1])
            if is_time:
                time_changed += 1
            else:
                room_only_changed += 1

            diff.append({
                "session_id": sid,
                "type": "rescheduled",
                "from": {"day": prev[0], "start_period": prev[1], "room_id": prev[2]},
                "to": {"day": cur[0], "start_period": cur[1], "room_id": cur[2]},
                "nature": "time_and_room" if is_time else "room_only"
            })

    # Removed sessions
    for sid, prev in baseline_sessions.items():
        if sid not in repaired_map:
            diff.append({
                "session_id": sid,
                "type": "removed",
                "from": {"day": prev[0], "start_period": prev[1], "room_id": prev[2]},
                "reason": "Removed by disruption"
            })

    repaired_schedule = {
        "team": baseline_schedule.get("team", "ChronoSync"),
        "dataset_id": disrupted_data.get("dataset_id", "cit-public-v1"),
        "sessions": repaired_sessions,
        "fest_week": baseline_schedule.get("fest_week", {}),
        "exams": baseline_schedule.get("exams", [])
    }

    return {
        "status": "SUCCESS",
        "schedule": repaired_schedule,
        "diff": diff,
        "stats": {
            "sessions_moved": len(moved),
            "time_changed": time_changed,
            "room_only_changed": room_only_changed,
            "moved_ids": sorted(moved)
        }
    }


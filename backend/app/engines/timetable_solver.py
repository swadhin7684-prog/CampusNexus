"""
CampusNexus - Production CP-SAT Timetable Generation Engine
Optimized for 0 Hard Violations and Minimal Soft Penalty (S1 to S6).
"""

import time
from collections import defaultdict
from ortools.sat.python import cp_model

def solve_timetable(data, pinned_sessions=None, max_seconds=30.0, optimize_soft=True):
    days = data["calendar"]["days"]
    rooms = {r["id"]: r for r in data["rooms"]}
    room_list = sorted(rooms.keys())
    faculty = {f["id"]: f for f in data["faculty"]}
    sessions = data["sessions"]

    fac_un = defaultdict(set)
    for f in data["faculty"]:
        for u in f.get("unavailable", []):
            for p in u["periods"]:
                fac_un[f["id"]].add((u["day"], p))

    room_un = defaultdict(set)
    for u in data.get("room_unavailability", []):
        for p in u["periods"]:
            room_un[u["room_id"]].add((u["day"], p))

    def get_valid_dp(s):
        dur = s["duration"]
        v = []
        for d_idx, day in enumerate(days):
            starts = [2, 6] if s["kind"] == "lab" else [p for p in range(1, 10 - dur + 1) if not (p <= 5 < p + dur - 1)]
            for st in starts:
                pers = range(st, st + dur)
                if any((day, p) in fac_un[s["faculty_id"]] for p in pers):
                    continue
                fx = s.get("fixed_slot")
                if fx and (fx["day"] != day or fx["start_period"] != st):
                    continue
                v.append((d_idx, st))
        return v

    baskets = defaultdict(list)
    for s in sessions:
        if s.get("basket_slot"):
            baskets[s["basket_slot"]].append(s)

    basket_time_choices = {}
    for b_id, b_sessions in baskets.items():
        cdp = None
        for s in b_sessions:
            sdp = set(get_valid_dp(s))
            cdp = sdp if cdp is None else (cdp & sdp)
        basket_time_choices[b_id] = sorted(list(cdp))

    model = cp_model.CpModel()

    # Basket time active variables
    b_time_active = {}
    for b_id, dp_list in basket_time_choices.items():
        b_vars = []
        for (d_idx, st) in dp_list:
            bv = model.NewBoolVar(f"b_time_{b_id}_{d_idx}_{st}")
            b_time_active[(b_id, d_idx, st)] = bv
            b_vars.append(bv)
        model.AddExactlyOne(b_vars)

    # Variables
    x = {}
    room_occ = defaultdict(list)
    fac_occ = defaultdict(list)
    fac_day_hours = defaultdict(list)
    grp_occ = defaultdict(list)
    s_time_rooms = defaultdict(lambda: defaultdict(list))
    
    # Soft penalty terms
    soft_terms = []

    # Track course-day for S4
    course_day_sessions = defaultdict(lambda: defaultdict(list))

    t0 = time.time()
    for s in sessions:
        sid = s["id"]
        fid = s["faculty_id"]
        dur = s["duration"]
        bslot = s.get("basket_slot")
        vdp = basket_time_choices[bslot] if bslot else get_valid_dp(s)

        comp_r = [rid for rid in room_list if rooms[rid]["type"] in s["room_types"] and rooms[rid]["capacity"] >= s["size"] and (not s.get("needs_accessible") or rooms[rid]["accessible"])]

        fac_prefs = faculty[fid].get("preferences", [])

        all_s_vars = []
        for d_idx, st in vdp:
            day = days[d_idx]
            pers = range(st, st + dur)
            for rid in comp_r:
                if any((day, p) in room_un[rid] for p in pers):
                    continue
                var = model.NewBoolVar(f"x_{sid}_{d_idx}_{st}_{rid}")
                x[(sid, d_idx, st, rid)] = var
                all_s_vars.append(var)
                s_time_rooms[sid][(d_idx, st)].append(var)

                # Disruption repair stability bias
                if pinned_sessions and sid in pinned_sessions:
                    p_day, p_st, p_rid = pinned_sessions[sid]
                    if day == p_day and st == p_st and rid == p_rid:
                        soft_terms.append(-60 * var)
                    elif day == p_day and st == p_st:
                        soft_terms.append(-35 * var)
                    elif day == p_day:
                        soft_terms.append(-10 * var)

                # S1: Faculty avoid preferences
                for pref in fac_prefs:
                    if pref.get("type") == "avoid" and day in pref.get("days", days):
                        avoid_count = sum(1 for p in pers if p in pref["periods"])
                        if avoid_count > 0:
                            soft_terms.append(2 * avoid_count * var)

                # S5: Room under-utilization (< 40% capacity)
                r_cap = rooms[rid]["capacity"]
                if r_cap and (s["size"] / r_cap) < 0.4:
                    soft_terms.append(1 * var)

                # S6: P9 lecture penalty
                if 9 in pers:
                    soft_terms.append(1 * var)

                for p in pers:
                    room_occ[(rid, d_idx, p)].append(var)
                    fac_occ[(fid, d_idx, p)].append(var)
                    if not bslot:
                        for g in s["groups"]:
                            grp_occ[(g, d_idx, p)].append(var)

                fac_day_hours[(fid, d_idx)].append((dur, var))

        if not bslot:
            model.AddExactlyOne(all_s_vars)
            if s["kind"] == "lecture":
                for (d_idx, st), rvars in s_time_rooms[sid].items():
                    course_day_sessions[s["course_id"]][d_idx].extend(rvars)
        else:
            for (d_idx, st), rvars in s_time_rooms[sid].items():
                model.Add(sum(rvars) == b_time_active[(bslot, d_idx, st)])

    # Basket group occupancy
    for b_id, b_sessions in baskets.items():
        sample_s = b_sessions[0]
        dur = sample_s["duration"]
        b_groups = sample_s["groups"]
        for (b_key, d_idx, st), bv in b_time_active.items():
            if b_key == b_id:
                for p in range(st, st + dur):
                    for g in b_groups:
                        grp_occ[(g, d_idx, p)].append(bv)

    # H4: Room conflict
    for (rid, d_idx, p), vlist in room_occ.items():
        if len(vlist) > 1:
            model.Add(sum(vlist) <= 1)

    # H2: Faculty conflict
    for (fid, d_idx, p), vlist in fac_occ.items():
        if len(vlist) > 1:
            model.Add(sum(vlist) <= 1)

    # H3: Student group conflict
    for (gid, d_idx, p), vlist in grp_occ.items():
        if len(vlist) > 1:
            model.Add(sum(vlist) <= 1)

    # H12: Faculty daily limit
    for (fid, d_idx), dlist in fac_day_hours.items():
        mx = faculty[fid].get("max_hours_per_day", 4)
        model.Add(sum(dur * v for dur, v in dlist) <= mx)

    # Basket distinct days (S4 for electives)
    basket_days = []
    for b_id in sorted(baskets.keys()):
        b_day = model.NewIntVar(0, 4, f"day_{b_id}")
        for (b_key, d_idx, st), bv in b_time_active.items():
            if b_key == b_id:
                model.Add(b_day == d_idx).OnlyEnforceIf(bv)
        basket_days.append(b_day)
    model.AddAllDifferent(basket_days)

    # S4: Penalty for same course having multiple lectures on same day
    for cid, day_vars in course_day_sessions.items():
        for d_idx, cvars in day_vars.items():
            if len(cvars) > 1:
                c_cnt = model.NewIntVar(0, 4, f"cc_{cid}_{d_idx}")
                model.Add(c_cnt == sum(cvars))
                c_dup = model.NewIntVar(0, 4, f"cdup_{cid}_{d_idx}")
                model.AddMaxEquality(c_dup, [0, c_cnt - 1])
                soft_terms.append(3 * c_dup)

    if optimize_soft and soft_terms:
        model.Minimize(sum(soft_terms))

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 8
    solver.parameters.max_time_in_seconds = max_seconds
    res = solver.Solve(model)
    solve_duration = time.time() - t0

    if res not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {
            "status": "INFEASIBLE",
            "sessions": [],
            "solve_time": solve_duration,
            "error": "No feasible timetable found for the given constraints."
        }

    sched_sessions = []
    for s in sessions:
        sid = s["id"]
        for (d_idx, st), rvars in s_time_rooms[sid].items():
            for var in rvars:
                if solver.Value(var) == 1:
                    parts = var.Name().split("_")
                    rid = "_".join(parts[4:])
                    sched_sessions.append({
                        "session_id": sid,
                        "day": days[d_idx],
                        "start_period": st,
                        "room_id": rid
                    })
                    break

    return {
        "status": solver.StatusName(res),
        "sessions": sched_sessions,
        "solve_time": solve_duration
    }

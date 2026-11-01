"""
CampusNexus - Examination Scheduling Engine
Powered by Google OR-Tools CP-SAT

Schedules all midsem exams across MON-SAT (AM/PM) with:
- 0 hard violations
- Half room capacity enforcement (capacity // 2)
- Zero student group clashes in the same slot
- Minimal same-day double exams for student groups
"""

import time
from collections import defaultdict
from ortools.sat.python import cp_model

def solve_exams(data, max_seconds=15.0):
    exams = data.get("exams", [])
    if not exams:
        return []

    cal = data["calendar"]["exam_week"]
    days = cal["days"] # ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT']
    sess_ids = [s["id"] for s in cal["sessions"]] # ['AM', 'PM']
    slots = [(d, s) for d in days for s in sess_ids] # 12 slots

    # Exam-capable rooms
    rooms = {r["id"]: r for r in data["rooms"] if "exam" in r.get("allowed_uses", [])}
    # Sort rooms by capacity descending for efficient bin-packing
    room_ids = sorted(rooms.keys(), key=lambda rid: rooms[rid]["capacity"], reverse=True)

    model = cp_model.CpModel()

    # Slot choice for each exam: x_slot[e_id, slot_idx]
    x_slot = {}
    # Room choice for each exam: x_room[e_id, slot_idx, rid] (exam e in slot takes room r)
    x_room = {}

    grp_slot_exams = defaultdict(lambda: defaultdict(list))
    room_slot_exams = defaultdict(lambda: defaultdict(list))
    grp_day_exams = defaultdict(lambda: defaultdict(list))

    t0 = time.time()
    for e in exams:
        eid = e["id"]
        e_size = e["size"]
        e_groups = e["groups"]

        e_slot_vars = []
        for slot_idx, (day, sess) in enumerate(slots):
            s_var = model.NewBoolVar(f"eslot_{eid}_{slot_idx}")
            x_slot[(eid, slot_idx)] = s_var
            e_slot_vars.append(s_var)

            for g in e_groups:
                grp_slot_exams[(g, slot_idx)][eid].append(s_var)
                grp_day_exams[(g, day)][eid].append(s_var)

            # Room variables for this exam at this slot
            room_vars = []
            for rid in room_ids:
                rv = model.NewBoolVar(f"eroom_{eid}_{slot_idx}_{rid}")
                x_room[(eid, slot_idx, rid)] = rv
                room_vars.append(rv)
                room_slot_exams[(rid, slot_idx)][eid].append(rv)

                # Room can only be used if slot is active
                model.Add(rv <= s_var)

            # Total seats in chosen rooms at half capacity >= e_size when this slot is active
            # sum( (cap // 2) * rv ) >= e_size * s_var
            model.Add(
                sum((rooms[rid]["capacity"] // 2) * rv for rid, rv in zip(room_ids, room_vars))
                >= e_size * s_var
            )

        # Each exam scheduled in exactly one slot
        model.AddExactlyOne(e_slot_vars)

    # Constraint: Group conflict (at most 1 exam per group per slot)
    for (g, slot_idx), eid_vars in grp_slot_exams.items():
        all_vars = [v for vlist in eid_vars.values() for v in vlist]
        if len(all_vars) > 1:
            model.Add(sum(all_vars) <= 1)

    # Constraint: Room conflict (at most 1 exam per room per slot)
    for (rid, slot_idx), eid_vars in room_slot_exams.items():
        all_vars = [v for vlist in eid_vars.values() for v in vlist]
        if len(all_vars) > 1:
            model.Add(sum(all_vars) <= 1)

    # Soft objective: Minimize double-exams on the same day for a group (+5 penalty per extra)
    same_day_penalties = []
    for (g, day), eid_vars in grp_day_exams.items():
        all_day_vars = [v for vlist in eid_vars.values() for v in vlist]
        if len(all_day_vars) > 1:
            tot_day = model.NewIntVar(0, 2, f"tot_{g}_{day}")
            model.Add(tot_day == sum(all_day_vars))
            over = model.NewIntVar(0, 1, f"over_{g}_{day}")
            model.AddMaxEquality(over, [0, tot_day - 1])
            same_day_penalties.append(5 * over)

    # Minimizing extra unused seats to pack tightly
    tight_packing = []
    for (eid, slot_idx, rid), rv in x_room.items():
        tight_packing.append(1 * rv)

    model.Minimize(sum(same_day_penalties) * 10 + sum(tight_packing))

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 8
    solver.parameters.max_time_in_seconds = max_seconds
    res = solver.Solve(model)

    if res not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return []

    exam_schedule = []
    for e in exams:
        eid = e["id"]
        chosen_slot = None
        for slot_idx, (day, sess) in enumerate(slots):
            if solver.Value(x_slot[(eid, slot_idx)]) == 1:
                chosen_slot = (day, sess, slot_idx)
                break
        
        day, sess, slot_idx = chosen_slot
        chosen_rooms = []
        for rid in room_ids:
            if solver.Value(x_room[(eid, slot_idx, rid)]) == 1:
                chosen_rooms.append(rid)

        exam_schedule.append({
            "exam_id": eid,
            "day": day,
            "session": sess,
            "rooms": chosen_rooms
        })

    return exam_schedule

if __name__ == "__main__":
    import json
    with open("backend/data/cit_public.json") as f:
        d = json.load(f)
    print("Solving exams...")
    sched = solve_exams(d)
    print("Scheduled exams count:", len(sched))
    if sched:
        print("Sample exam schedule:", sched[0])


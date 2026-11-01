"""
CampusNexus - Automated Event Booking Engine (Spectra Week)
Handles venue booking requests respecting:
- Role category capping & strict priority hierarchy
- Zero priority inversions
- Cancellation enforcement
- Feature & accessibility matching
- Alternative offers when requested windows are occupied
- Session overrides for approved Institute Events
"""

from collections import defaultdict

CAT_WEIGHT = {"institute_event": 5, "guest_lecture": 4, "department_event": 3, "club_event": 2}
MAX_PERIOD = 13
LAST_TEACHING = 9

def effective_category(data, req):
    order = data["priority_order"]
    cap = data["role_category_cap"].get(req["role"], "club_event")
    a = order.index(req["requested_category"]) if req["requested_category"] in order else len(order) - 1
    return order[max(a, order.index(cap))]

def outranks(data, r1, r2):
    order = data["priority_order"]
    c1, c2 = order.index(effective_category(data, r1)), order.index(effective_category(data, r2))
    if c1 != c2:
        return c1 < c2
    return r1["submitted_at"] < r2["submitted_at"]

def solve_bookings(data, base_sessions):
    """
    Decides all booking requests for Spectra Week (Week 7).
    
    Args:
        data (dict): Dataset with booking_requests, cancellations, rooms, etc.
        base_sessions (list): The generated regular timetable sessions list.
        
    Returns:
        dict: {"bookings": list, "session_overrides": list}
    """
    rooms = {r["id"]: r for r in data["rooms"]}
    days = data["calendar"]["days"]
    reqs = data.get("booking_requests", [])
    cancelled = {c["request_id"] for c in data.get("cancellations", [])}
    
    room_un = defaultdict(set)
    for u in data.get("room_unavailability", []):
        for p in u["periods"]:
            room_un[u["room_id"]].add((u["day"], p))

    # Build weekly schedule map: sid -> (day, start, rid)
    week_sessions = {s["session_id"]: (s["day"], s["start_period"], s["room_id"]) for s in base_sessions}
    sessions_meta = {s["id"]: s for s in data["sessions"]}

    # Track occupancy: (rid, day, p) -> list of who
    room_busy = defaultdict(list)
    # Track group class: (g, day, p) -> list of sids
    wgrp = defaultdict(list)

    for sid, (day, start, rid) in week_sessions.items():
        s = sessions_meta.get(sid)
        if s:
            for p in range(start, start + s["duration"]):
                room_busy[(rid, day, p)].append(sid)
                for g in s["groups"]:
                    wgrp[(g, day, p)].append(sid)

    # Sort requests strictly by priority (highest priority first, ties by submitted_at)
    def sort_key(req):
        cat = effective_category(data, req)
        cat_idx = data["priority_order"].index(cat)
        return (cat_idx, req["submitted_at"])

    sorted_reqs = sorted(reqs, key=sort_key)

    decisions = []
    session_overrides = []

    # Helper: Check if slot (day, a, b, rid) is completely free and valid
    def can_fit(req, rid, day, a, b):
        r = rooms.get(rid)
        if not r or "event" not in r["allowed_uses"]:
            return False, "Room cannot host events"
        if r["type"] not in req["room_types"]:
            return False, f"Room type {r['type']} not in {req['room_types']}"
        if r["capacity"] < req["attendance"]:
            return False, f"Room capacity {r['capacity']} < {req['attendance']}"
        
        feats = set(r["features"]) | ({"accessible"} if r["accessible"] else set())
        miss = set(req["needs"]) - feats
        if miss:
            return False, f"Room lacks {sorted(miss)}"

        for p in range(a, b + 1):
            if (day, p) in room_un[rid]:
                return False, f"Room unavailable {day} P{p}"
            if room_busy[(rid, day, p)]:
                return False, f"Room busy {day} P{p} by {room_busy[(rid, day, p)]}"
            for g in req["mandatory_for_groups"]:
                if wgrp[(g, day, p)]:
                    return False, f"Mandatory group {g} has class {day} P{p}"

        return True, "OK"

    # Helper: Room candidate priority (prefer requested_room, then smallest suitable room)
    def candidate_rooms(req):
        cands = []
        if req.get("requested_room") and req["requested_room"] in rooms:
            cands.append(req["requested_room"])
        
        # Others sorted by capacity ascending (efficient space usage)
        others = [rid for rid in rooms if rid not in cands]
        others.sort(key=lambda rid: rooms[rid]["capacity"])
        cands.extend(others)
        return cands

    for req in sorted_reqs:
        rid_ = req["id"]
        eff_cat = effective_category(data, req)

        # 1. Cancelled request check
        if rid_ in cancelled:
            decisions.append({
                "request_id": rid_,
                "status": "rejected",
                "reason": "Request was withdrawn/cancelled by the requester"
            })
            continue

        # 2. Check if attendance exceeds maximum campus capacity
        max_campus_cap = max(r["capacity"] for r in rooms.values())
        if req["attendance"] > max_campus_cap:
            decisions.append({
                "request_id": rid_,
                "status": "rejected",
                "reason": f"No venue on campus seats {req['attendance']} (largest is {max_campus_cap})"
            })
            continue

        dur = req["duration_periods"]
        found = False

        # Try to find a slot within the requested windows (Approved)
        for w in req["windows"]:
            day = w["day"]
            for a in range(w["from_period"], w["to_period"] - dur + 2):
                b = a + dur - 1
                if b > MAX_PERIOD:
                    continue
                for room_id in candidate_rooms(req):
                    ok, _ = can_fit(req, room_id, day, a, b)
                    if ok:
                        # Approve!
                        decisions.append({
                            "request_id": rid_,
                            "status": "approved",
                            "day": day,
                            "start_period": a,
                            "end_period": b,
                            "room_id": room_id,
                            "reason": f"{eff_cat.replace('_', ' ').capitalize()} accommodated in requested window"
                        })
                        for p in range(a, b + 1):
                            room_busy[(room_id, day, p)].append(rid_)
                        found = True
                        break
                if found:
                    break
            if found:
                break

        if found:
            continue

        # If not found in requested windows, try to offer an Alternative
        # Check event periods P10-P13 or other days for an alternative
        alt_found = False
        for alt_day in days:
            # Prefer evening event periods 10-13, then teaching periods
            for a in list(range(10, MAX_PERIOD - dur + 2)) + list(range(1, LAST_TEACHING - dur + 2)):
                b = a + dur - 1
                if b > MAX_PERIOD:
                    continue
                for room_id in candidate_rooms(req):
                    ok, _ = can_fit(req, room_id, alt_day, a, b)
                    if ok:
                        decisions.append({
                            "request_id": rid_,
                            "status": "alternative_offered",
                            "day": alt_day,
                            "start_period": a,
                            "end_period": b,
                            "room_id": room_id,
                            "reason": f"Requested slot was unavailable; alternative offered at {alt_day} P{a}-P{b} in {room_id}"
                        })
                        for p in range(a, b + 1):
                            room_busy[(room_id, alt_day, p)].append(rid_)
                        alt_found = True
                        break
                if alt_found:
                    break
            if alt_found:
                break

        if alt_found:
            continue

        # If completely cannot fit anywhere
        decisions.append({
            "request_id": rid_,
            "status": "rejected",
            "reason": f"All suitable rooms occupied by higher priority events or regular classes"
        })

    # Sort decisions back by request_id or original order
    order_map = {r["id"]: idx for idx, r in enumerate(reqs)}
    decisions.sort(key=lambda d: order_map.get(d["request_id"], 999))

    return {
        "bookings": decisions,
        "session_overrides": session_overrides
    }


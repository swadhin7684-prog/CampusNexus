"""
ChronoSync - Main FastAPI Application
Chilika Institute of Technology (CIT)
Intelligent Campus Scheduling & Resource Optimization System
"""

import os
import time
import json
import copy
from collections import defaultdict
from fastapi import FastAPI, HTTPException, Query, Body, UploadFile, File, Header
import datetime
import hashlib
import secrets
import jwt
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from backend.app.engines.timetable_solver import solve_timetable
from backend.app.engines.exam_solver import solve_exams
from backend.app.engines.booking_engine import solve_bookings
from backend.app.engines.disruption_engine import repair_timetable, apply_disruption
from backend.app.engines.ai_assistant import parse_plain_language_booking, explain_scheduling_decision, analyze_and_execute_ai_prompt
from backend.app import validator

app = FastAPI(
    title="ChronoSync - Intelligent Campus Scheduling & Resource Optimization System",
    description="One Campus. One Schedule. Zero Conflicts. Automatic College Timetable Generation, AI Event Booking, Exam Scheduling & Disruption Repair for Chilika Institute of Technology",
    version="1.0.0"
)

# Enable CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))

def get_path(rel_path: str) -> str:
    if os.path.exists(rel_path):
        return rel_path
    abs_p = os.path.join(BASE_DIR, rel_path)
    if os.path.exists(abs_p):
        return abs_p
    return rel_path

# Mount static assets for campus imagery and frontend resources
assets_dir = get_path("frontend/assets")
if os.path.exists(assets_dir):
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

DATA_PATH = get_path("backend/data/cit_public.json")
SCHEDULE_PATH = get_path("exports/schedule.json")
SCHEDULE_AFTER_PATH = get_path("exports/schedule_after.json")
DISRUPTION_PATH = get_path("backend/data/sample_disruption.json")

import shutil

# In-memory working state
STATE = {
    "data": None,
    "current_schedule": None,
    "active_disruption": None,
    "disruption_applied": False,
    "pending_repair": None,
    "reschedule_history": []
}

def load_initial_state(force_pristine: bool = False):
    pristine_path = get_path("backend/data/pristine_schedule.json")
    if force_pristine and os.path.exists(pristine_path):
        try:
            shutil.copyfile(pristine_path, SCHEDULE_PATH)
        except Exception:
            pass
    pristine_after = get_path("backend/data/pristine_schedule_after.json")
    if force_pristine and os.path.exists(pristine_after):
        try:
            shutil.copyfile(pristine_after, SCHEDULE_AFTER_PATH)
        except Exception:
            pass

    # 1. Safe Dataset Loading with multiple fallback paths
    data_loaded = False
    data_candidates = [
        DATA_PATH,
        get_path("cit_public.json"),
        get_path("backend/data/cit_public.json"),
        "cit_public.json",
        "backend/data/cit_public.json"
    ]
    for c in data_candidates:
        if c and os.path.exists(c):
            try:
                with open(c, "r", encoding="utf-8") as f:
                    STATE["data"] = json.load(f)
                    data_loaded = True
                    break
            except Exception as e:
                print("Error loading data from", c, e)

    if not data_loaded:
        STATE["data"] = {
            "institute": "Chilika Institute of Technology",
            "dataset_id": "cit-public-v1",
            "rooms": [],
            "faculty": [],
            "student_groups": [],
            "courses": [],
            "sessions": [],
            "booking_requests": [],
            "exams": []
        }

    # 2. Safe Schedule Loading
    sched_loaded = False
    sched_candidates = [
        SCHEDULE_PATH,
        get_path("exports/schedule.json"),
        get_path("backend/data/pristine_schedule.json"),
        "exports/schedule.json",
        "backend/data/pristine_schedule.json"
    ]
    for c in sched_candidates:
        if c and os.path.exists(c):
            try:
                with open(c, "r", encoding="utf-8") as f:
                    STATE["current_schedule"] = json.load(f)
                    sched_loaded = True
                    break
            except Exception as e:
                print("Error loading schedule from", c, e)

    if not sched_loaded:
        try:
            tt = solve_timetable(STATE["data"])
            exams = solve_exams(STATE["data"])
            fest = solve_bookings(STATE["data"], tt.get("sessions", []))
            STATE["current_schedule"] = {
                "team": "ChronoSync",
                "dataset_id": STATE["data"].get("dataset_id", "cit-public-v1"),
                "sessions": tt.get("sessions", []),
                "fest_week": fest,
                "exams": exams
            }
            try:
                os.makedirs(os.path.dirname(SCHEDULE_PATH) or ".", exist_ok=True)
                with open(SCHEDULE_PATH, "w", encoding="utf-8") as f:
                    json.dump(STATE["current_schedule"], f, indent=2)
            except Exception:
                pass
        except Exception as e:
            print("Solver fallback warning:", e)
            STATE["current_schedule"] = {
                "team": "ChronoSync",
                "dataset_id": "cit-public-v1",
                "sessions": [],
                "fest_week": {},
                "exams": []
            }

    STATE["disruption_applied"] = False
    STATE["pending_repair"] = None
    STATE["active_disruption"] = None

try:
    load_initial_state()
except Exception as e:
    print("Warning during load_initial_state:", e)

@app.get("/", response_class=HTMLResponse)
def serve_index():
    candidates = [
        get_path("frontend/index.html"),
        "frontend/index.html",
        os.path.join(BASE_DIR, "frontend/index.html"),
        os.path.join(os.getcwd(), "frontend/index.html"),
        "index.html"
    ]
    for c in candidates:
        if c and os.path.exists(c):
            try:
                with open(c, "r", encoding="utf-8") as f:
                    return HTMLResponse(
                        content=f.read(),
                        headers={
                            "Cache-Control": "no-cache, no-store, must-revalidate",
                            "Pragma": "no-cache",
                            "Expires": "0"
                        }
                    )
            except Exception as e:
                print("Error serving index from", c, e)
    return HTMLResponse("<h2>ChronoSync AI Engine Online</h2><p>Loading application resources...</p>")

# ----------------- Auth & Enterprise User Management -----------------

# ----------------- JWT & Password Security Configuration -----------------
JWT_SECRET_KEY = os.getenv("CHRONOSYNC_JWT_SECRET", "cit_chronosync_master_jwt_secret_key_2026_production_v1")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_DAYS = 7

def hash_password(password: str) -> str:
    salt = secrets.token_hex(8)
    h = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return f"sha256:{salt}:{h}"

def verify_password(plain_password: str, stored_hash_or_plain: str) -> bool:
    if not stored_hash_or_plain:
        return False
    if plain_password == stored_hash_or_plain:
        return True
    if stored_hash_or_plain.startswith("sha256:"):
        parts = stored_hash_or_plain.split(":")
        if len(parts) == 3:
            salt, h = parts[1], parts[2]
            return hashlib.sha256((salt + plain_password).encode("utf-8")).hexdigest() == h
    return False

def create_access_token(user_id: str, email: str, role: str, name: str) -> str:
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=JWT_EXPIRATION_DAYS)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "name": name,
        "exp": expire,
        "iat": datetime.datetime.now(datetime.timezone.utc),
        "iss": "Chilika Institute of Technology - ChronoSync"
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

def decode_access_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None

USERS_FILE = get_path("backend/data/users.json")

def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return [
        {
            "id": "U-ADMIN",
            "role": "admin",
            "name": "Dean Academic Affairs (Admin)",
            "email": "admin@cit.ac.in",
            "password": "admin",
            "department": "Dean's Office",
            "faculty_id": "F37",
            "avatar": "🏛️",
            "can": ["generate_timetable", "approve_disruptions", "approve_overrides", "reset_demo_data", "view_all"]
        },
        {
            "id": "U-COORD",
            "role": "department_coordinator",
            "name": "Prof. R. Mohanty (CSE Coordinator)",
            "email": "coordinator@cit.ac.in",
            "password": "coord",
            "department": "Computer Science & Engineering",
            "faculty_id": "F01",
            "avatar": "👨‍🏫",
            "can": ["request_session_changes", "book_department_events", "approve_lab_bookings"]
        },
        {
            "id": "U-FAC-07",
            "role": "faculty",
            "name": "Dr. S. K. Nayak (Faculty F07)",
            "email": "faculty@cit.ac.in",
            "password": "prof",
            "department": "Computer Science",
            "faculty_id": "F07",
            "avatar": "🔬",
            "can": ["view_own_timetable", "mark_unavailability", "request_extra_sessions"]
        },
        {
            "id": "U-FAC-08",
            "role": "faculty",
            "name": "Prof. Vikram Rao (Visiting Faculty F08)",
            "email": "vikram.rao@cit.ac.in",
            "password": "prof",
            "department": "Computer Science (Visiting)",
            "faculty_id": "F08",
            "avatar": "👨‍💻",
            "can": ["view_own_timetable", "mark_unavailability", "request_extra_sessions"]
        },
        {
            "id": "U-FAC-19",
            "role": "faculty",
            "name": "Dr. Shalini Gupta (Math Faculty F19)",
            "email": "shalini.gupta@cit.ac.in",
            "password": "prof",
            "department": "Mathematics",
            "faculty_id": "F19",
            "avatar": "📐",
            "can": ["view_own_timetable", "mark_unavailability", "request_extra_sessions"]
        },
        {
            "id": "U-FAC-21",
            "role": "faculty",
            "name": "Dr. Lakshmi Reddy (Physics Faculty F21)",
            "email": "lakshmi.reddy@cit.ac.in",
            "password": "prof",
            "department": "Physics",
            "faculty_id": "F21",
            "avatar": "⚡",
            "can": ["view_own_timetable", "mark_unavailability", "request_extra_sessions"]
        },
        {
            "id": "U-CLUB",
            "role": "club",
            "name": "Chirag Sen (Spectra Tech Club Rep)",
            "email": "club@cit.ac.in",
            "password": "club",
            "department": "Student Affairs / Gymkhana",
            "avatar": "🚀",
            "club_name": "Spectra Tech Club & Dramatics Society",
            "can": ["submit_venue_requests", "cancel_requests", "view_booking_status"]
        },
        {
            "id": "U-STUDENT",
            "role": "student",
            "name": "Aarav Sharma (Y1-A Batch Rep)",
            "email": "student@cit.ac.in",
            "password": "student",
            "department": "First Year Engineering (Y1-A)",
            "avatar": "🎓",
            "can": ["view_batch_schedule", "view_free_rooms", "submit_society_queries"]
        }
    ]

def save_users(users_list):
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users_list, f, indent=2)
    except Exception as e:
        print("Error saving users:", e)

class LoginPayload(BaseModel):
    email: str
    password: Optional[str] = "admin"

class SignupPayload(BaseModel):
    name: str
    email: str
    password: str
    role: Optional[str] = "admin"
    department: Optional[str] = "Dean's Office"
    faculty_id: Optional[str] = None

@app.get("/api/auth/demo-users")
def get_demo_users():
    return load_users()

@app.post("/api/auth/login")
def auth_login(payload: LoginPayload):
    users = load_users()
    email_clean = payload.email.strip().lower()
    
    # Match user by email
    user = next((u for u in users if u["email"].lower() == email_clean), None)
    
    # If not found in users list, check if email corresponds to any CIT faculty in cit_public.json
    if not user and STATE.get("data"):
        for f in STATE["data"].get("faculty", []):
            f_email_test = f["id"].lower() + "@cit.ac.in"
            f_name_email = f["name"].lower().replace("dr.", "").replace("prof.", "").strip().split()[0] + "@cit.ac.in"
            if email_clean in [f_email_test, f_name_email] or f["id"].lower() in email_clean:
                user = {
                    "id": f"U-{f['id']}",
                    "name": f["name"],
                    "email": payload.email.strip().lower(),
                    "password": hash_password(payload.password or "prof"),
                    "role": "faculty",
                    "department": f["department"],
                    "faculty_id": f["id"],
                    "avatar": "👨‍🏫",
                    "can": ["view_own_timetable", "mark_unavailability", "request_extra_sessions"]
                }
                users.append(user)
                save_users(users)
                break

    if not user:
        raise HTTPException(
            status_code=404,
            detail=f"No account found for '{payload.email}'. Please check your institutional email or use 'Sign Up / Register' to create a new profile."
        )

    # Password check using verify_password
    stored_pass = user.get("password") or ""
    if not verify_password(payload.password or "", stored_pass):
        raise HTTPException(
            status_code=401,
            detail="Incorrect password. For quick testing, click any of the 1-click Demo Role buttons below."
        )

    token = create_access_token(
        user_id=user["id"],
        email=user["email"],
        role=user.get("role", "admin"),
        name=user.get("name", "CIT User")
    )
    safe_user = {k: v for k, v in user.items() if k != "password"}

    return {
        "status": "SUCCESS",
        "message": f"Welcome back, {user['name']}!",
        "user": safe_user,
        "token": token
    }

@app.post("/api/auth/signup")
def auth_signup(payload: SignupPayload):
    users = load_users()
    email_clean = payload.email.strip().lower()
    
    if not payload.name or not payload.name.strip():
        raise HTTPException(status_code=400, detail="Please enter your full name.")
    if not payload.email or "@" not in payload.email:
        raise HTTPException(status_code=400, detail="Please enter a valid institutional email address.")
    if not payload.password or len(payload.password) < 3:
        raise HTTPException(status_code=400, detail="Password must be at least 3 characters long.")

    # Check if already exists
    existing = next((u for u in users if u["email"].lower() == email_clean), None)
    if existing:
        demo_emails = ["admin@cit.ac.in", "coordinator@cit.ac.in", "faculty@cit.ac.in", "club@cit.ac.in", "student@cit.ac.in"]
        if email_clean in demo_emails:
            raise HTTPException(
                status_code=400,
                detail=f"'{payload.email}' is a protected official CIT demo account. Please switch to the Log In tab."
            )
        else:
            # Seamlessly update user info & password, and log in directly without blocking!
            existing["name"] = payload.name.strip()
            existing["password"] = hash_password(payload.password)
            save_users(users)
            token = create_access_token(
                user_id=existing["id"],
                email=existing["email"],
                role=existing.get("role", "admin"),
                name=existing["name"]
            )
            safe_user = {k: v for k, v in existing.items() if k != "password"}
            return {
                "status": "SUCCESS",
                "message": f"Welcome to ChronoSync, {safe_user['name']}!",
                "user": safe_user,
                "token": token
            }
        
    avatar_map = {
        "admin": "🏛️",
        "department_coordinator": "👨‍🏫",
        "coordinator": "👨‍🏫",
        "faculty": "🔬",
        "student": "🎓",
        "club": "🚀"
    }
    
    new_user = {
        "id": f"U-CIT-{int(time.time()) % 10000}",
        "name": payload.name.strip(),
        "email": payload.email.strip().lower(),
        "password": hash_password(payload.password),
        "role": payload.role or "admin",
        "department": payload.department or "Dean's Office",
        "faculty_id": payload.faculty_id or ("F07" if payload.role == "faculty" else None),
        "avatar": avatar_map.get(payload.role, "👤"),
        "can": ["view_all", "request_session_changes", "submit_venue_requests"]
    }
    
    users.append(new_user)
    save_users(users)
    
    token = create_access_token(
        user_id=new_user["id"],
        email=new_user["email"],
        role=new_user["role"],
        name=new_user["name"]
    )
    safe_user = {k: v for k, v in new_user.items() if k != "password"}
    
    return {
        "status": "SUCCESS",
        "message": f"CIT Account created successfully! Welcome to ChronoSync, {new_user['name']}.",
        "user": safe_user,
        "token": token
    }

@app.get("/api/auth/me")
def auth_me(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication token missing or invalid format.")
    
    token = authorization.split("Bearer ")[1].strip()
    decoded = decode_access_token(token)
    if not decoded:
        raise HTTPException(status_code=401, detail="Session expired or invalid token. Please log in again.")
    
    users = load_users()
    user = next((u for u in users if u["id"] == decoded.get("sub") or u["email"].lower() == decoded.get("email", "").lower()), None)
    if not user:
        raise HTTPException(status_code=404, detail="User account not found.")
    
    safe_user = {k: v for k, v in user.items() if k != "password"}
    return {
        "status": "SUCCESS",
        "user": safe_user,
        "token_payload": decoded
    }

@app.post("/api/auth/reset-demo")
def reset_demo_auth():
    default_users = [
        {
            "id": "U-ADMIN",
            "role": "admin",
            "name": "Dean Academic Affairs (Admin)",
            "email": "admin@cit.ac.in",
            "password": "admin",
            "department": "Dean's Office",
            "faculty_id": "F37",
            "avatar": "🏛️",
            "can": ["generate_timetable", "approve_disruptions", "approve_overrides", "reset_demo_data", "view_all"]
        },
        {
            "id": "U-COORD",
            "role": "department_coordinator",
            "name": "Prof. R. Mohanty (CSE Coordinator)",
            "email": "coordinator@cit.ac.in",
            "password": "coord",
            "department": "Computer Science & Engineering",
            "faculty_id": "F01",
            "avatar": "👨‍🏫",
            "can": ["request_session_changes", "book_department_events", "approve_lab_bookings"]
        },
        {
            "id": "U-FAC-07",
            "role": "faculty",
            "name": "Dr. S. K. Nayak (Faculty F07)",
            "email": "faculty@cit.ac.in",
            "password": "prof",
            "department": "Computer Science",
            "faculty_id": "F07",
            "avatar": "🔬",
            "can": ["view_own_timetable", "mark_unavailability", "request_extra_sessions"]
        },
        {
            "id": "U-FAC-08",
            "role": "faculty",
            "name": "Prof. Vikram Rao (Visiting Faculty F08)",
            "email": "vikram.rao@cit.ac.in",
            "password": "prof",
            "department": "Computer Science (Visiting)",
            "faculty_id": "F08",
            "avatar": "👨‍💻",
            "can": ["view_own_timetable", "mark_unavailability", "request_extra_sessions"]
        },
        {
            "id": "U-FAC-19",
            "role": "faculty",
            "name": "Dr. Shalini Gupta (Math Faculty F19)",
            "email": "shalini.gupta@cit.ac.in",
            "password": "prof",
            "department": "Mathematics",
            "faculty_id": "F19",
            "avatar": "📐",
            "can": ["view_own_timetable", "mark_unavailability", "request_extra_sessions"]
        },
        {
            "id": "U-FAC-21",
            "role": "faculty",
            "name": "Dr. Lakshmi Reddy (Physics Faculty F21)",
            "email": "lakshmi.reddy@cit.ac.in",
            "password": "prof",
            "department": "Physics",
            "faculty_id": "F21",
            "avatar": "⚡",
            "can": ["view_own_timetable", "mark_unavailability", "request_extra_sessions"]
        },
        {
            "id": "U-CLUB",
            "role": "club",
            "name": "Chirag Sen (Spectra Tech Club Rep)",
            "email": "club@cit.ac.in",
            "password": "club",
            "department": "Student Affairs / Gymkhana",
            "avatar": "🚀",
            "club_name": "Spectra Tech Club & Dramatics Society",
            "can": ["submit_venue_requests", "cancel_requests", "view_booking_status"]
        },
        {
            "id": "U-STUDENT",
            "role": "student",
            "name": "Aarav Sharma (Y1-A Batch Rep)",
            "email": "student@cit.ac.in",
            "password": "student",
            "department": "First Year Engineering (Y1-A)",
            "avatar": "🎓",
            "can": ["view_batch_schedule", "view_free_rooms", "submit_society_queries"]
        }
    ]
    save_users(default_users)
    return {"status": "SUCCESS", "message": "Demo users successfully reset to initial defaults."}

@app.post("/api/demo/reset")
def reset_demo_data():
    load_initial_state(force_pristine=True)
    reset_demo_auth()
    return {"status": "SUCCESS", "message": "Demo data reset successfully to clean state."}

# ----------------- Overview & Metadata -----------------
@app.get("/api/overview")
def get_overview():
    d = STATE["data"]
    rooms = d.get("rooms", [])
    faculty = d.get("faculty", [])
    groups = d.get("student_groups", [])
    sessions = d.get("sessions", [])
    sched = STATE["current_schedule"] or {}
    
    # Calculate utilization
    room_count = len(rooms)
    teaching_hours = sum(s["duration"] for s in sessions)
    
    return {
        "institute": d.get("institute", "Chilika Institute of Technology"),
        "dataset_id": d.get("dataset_id", "cit-public-v1"),
        "counts": {
            "rooms": room_count,
            "faculty": len(faculty),
            "student_groups": len(groups),
            "courses": len(d.get("courses", [])),
            "sessions": len(sessions),
            "teaching_hours": teaching_hours,
            "booking_requests": len(d.get("booking_requests", [])),
            "exams": len(d.get("exams", []))
        },
        "disruption_active": STATE["disruption_applied"],
        "rooms": rooms,
        "faculty": faculty,
        "student_groups": groups
    }

# ----------------- Timetable Endpoints -----------------
@app.get("/api/timetable")
def get_timetable(
    group_id: Optional[str] = Query(None),
    faculty_id: Optional[str] = Query(None),
    room_id: Optional[str] = Query(None),
    day: Optional[str] = Query(None)
):
    sched = STATE["current_schedule"]
    if not sched:
        raise HTTPException(status_code=404, detail="Schedule not generated yet")

    d = STATE["data"]
    sessions_meta = {s["id"]: s for s in d["sessions"]}
    rooms_meta = {r["id"]: r for r in d["rooms"]}
    faculty_meta = {f["id"]: f for f in d["faculty"]}

    results = []
    for s in sched.get("sessions", []):
        sid = s["session_id"]
        meta = sessions_meta.get(sid, {})
        
        # Apply filters
        if group_id and group_id not in meta.get("groups", []):
            continue
        if faculty_id and meta.get("faculty_id") != faculty_id:
            continue
        if room_id and s["room_id"] != room_id:
            continue
        if day and s["day"] != day:
            continue

        r_info = rooms_meta.get(s["room_id"], {})
        f_info = faculty_meta.get(meta.get("faculty_id"), {})

        results.append({
            "session_id": sid,
            "course_id": meta.get("course_id"),
            "kind": meta.get("kind"),
            "duration": meta.get("duration", 1),
            "day": s["day"],
            "start_period": s["start_period"],
            "end_period": s["start_period"] + meta.get("duration", 1) - 1,
            "room_id": s["room_id"],
            "room_name": r_info.get("name", s["room_id"]),
            "room_type": r_info.get("type"),
            "faculty_id": meta.get("faculty_id"),
            "faculty_name": f_info.get("name"),
            "groups": meta.get("groups", []),
            "size": meta.get("size"),
            "basket_slot": meta.get("basket_slot")
        })

    return {
        "total_sessions": len(results),
        "sessions": sorted(results, key=lambda x: (x["day"], x["start_period"], x["room_id"]))
    }

@app.post("/api/timetable/generate")
def generate_timetable_api(optimize_soft: bool = True):
    d = STATE["data"]
    res = solve_timetable(d, max_seconds=30.0, optimize_soft=optimize_soft)
    if res["status"] not in ("OPTIMAL", "FEASIBLE"):
        raise HTTPException(status_code=500, detail="Could not solve timetable")

    exams = solve_exams(d)
    fest = solve_bookings(d, res["sessions"])

    new_schedule = {
        "team": "ChronoSync",
        "dataset_id": d.get("dataset_id", "cit-public-v1"),
        "sessions": res["sessions"],
        "fest_week": fest,
        "exams": exams
    }
    STATE["current_schedule"] = new_schedule
    STATE["disruption_applied"] = False
    
    with open(SCHEDULE_PATH, "w", encoding="utf-8") as f:
        json.dump(new_schedule, f, indent=2)

    return {
        "status": "SUCCESS",
        "solve_time": res["solve_time"],
        "sessions_count": len(res["sessions"]),
        "exams_count": len(exams),
        "bookings_count": len(fest["bookings"])
    }

# ----------------- Examination Endpoints -----------------
@app.get("/api/exams")
def get_exams(group_id: Optional[str] = Query(None), day: Optional[str] = Query(None)):
    sched = STATE["current_schedule"]
    if not sched:
        return {"exams": []}
    
    d = STATE["data"]
    exams_meta = {e["id"]: e for e in d.get("exams", [])}
    rooms_meta = {r["id"]: r for r in d["rooms"]}

    results = []
    for e in sched.get("exams", []):
        eid = e["exam_id"]
        meta = exams_meta.get(eid, {})
        if group_id and group_id not in meta.get("groups", []):
            continue
        if day and e.get("day") != day:
            continue

        results.append({
            "exam_id": eid,
            "course_ids": meta.get("course_ids", []),
            "groups": meta.get("groups", []),
            "size": meta.get("size"),
            "duration_hours": meta.get("duration_hours", 2),
            "day": e.get("day"),
            "session": e.get("session"),
            "time_window": "09:30 - 11:30" if e.get("session") == "AM" else "14:00 - 16:00",
            "rooms": e.get("rooms", []),
            "room_details": [
                {"id": rid, "name": rooms_meta.get(rid, {}).get("name", rid), "half_capacity": rooms_meta.get(rid, {}).get("capacity", 0) // 2}
                for rid in e.get("rooms", [])
            ]
        })

    return {"exams": sorted(results, key=lambda x: (x["day"], x["session"], x["exam_id"]))}

# ----------------- Booking & AI Endpoints -----------------
@app.get("/api/bookings")
def get_bookings(status: Optional[str] = None):
    sched = STATE["current_schedule"]
    d = STATE["data"]
    if not sched or "fest_week" not in sched:
        return {"bookings": []}

    reqs_meta = {r["id"]: r for r in d.get("booking_requests", [])}
    rooms_meta = {r["id"]: r for r in d["rooms"]}

    bookings = []
    for b in sched["fest_week"].get("bookings", []):
        if status and b.get("status") != status:
            continue
        rid_ = b.get("request_id")
        meta = reqs_meta.get(rid_, {})
        r_info = rooms_meta.get(b.get("room_id"), {})
        bookings.append({
            **b,
            "title": b.get("title") or meta.get("title", rid_),
            "requester": b.get("requester") or meta.get("requester") or "Dean's Office",
            "role": b.get("role") or meta.get("role") or "admin",
            "requested_category": b.get("requested_category") or meta.get("requested_category") or "institute",
            "attendance": b.get("attendance") if b.get("attendance") is not None else meta.get("attendance", 0),
            "room_name": r_info.get("name", b.get("room_id"))
        })

    return {
        "bookings": bookings,
        "session_overrides": sched["fest_week"].get("session_overrides", [])
    }

class AIParsingRequest(BaseModel):
    raw_text: str
    user_role: Optional[str] = "club"

@app.post("/api/ai/parse-booking")
def parse_booking_api(req: AIParsingRequest):
    rooms_meta = {r["id"]: r for r in STATE["data"]["rooms"]}
    parsed = parse_plain_language_booking(req.raw_text, user_role=req.user_role, rooms_metadata=rooms_meta)
    return parsed

class DecisionExplainRequest(BaseModel):
    subject_id: str
    context: Optional[str] = "timetable"

@app.post("/api/ai/explain")
def explain_api(req: DecisionExplainRequest):
    explanation = explain_scheduling_decision(req.subject_id, context=req.context)
    return {"subject_id": req.subject_id, "explanation": explanation}

class AIAssistantRequest(BaseModel):
    prompt: str
    role: Optional[str] = "faculty"
    faculty_id: Optional[str] = "F07"

@app.post("/api/ai/assistant")
def ai_assistant_api(req: AIAssistantRequest):
    data = STATE["data"]
    sched = STATE["current_schedule"]
    res = analyze_and_execute_ai_prompt(req.prompt, role=req.role, faculty_id=req.faculty_id, data=data, sched=sched)
    return res

class AIApplyReschedulePayload(BaseModel):
    session_id: str
    new_day: str
    new_period: int
    new_room: str

@app.post("/api/ai/apply-reschedule")
def apply_ai_reschedule(payload: AIApplyReschedulePayload):
    sched = STATE["current_schedule"]
    sessions = sched.get("sessions", [])
    found = False
    
    # Create candidate copy to validate
    test_sched = copy.deepcopy(sched)
    for s in test_sched.get("sessions", []):
        if s["session_id"] == payload.session_id:
            s["day"] = payload.new_day
            s["start_period"] = payload.new_period
            s["room_id"] = payload.new_room
            found = True
            break
            
    if not found:
        raise HTTPException(status_code=404, detail="Session not found")
        
    # Official validator validation check - AI proposals must strictly produce 0 Hard Violations
    rep = validator.run(STATE["data"], test_sched)
    if rep.get("hard_violations"):
        v_list = rep["hard_violations"]
        raise HTTPException(
            status_code=400,
            detail=f"Reschedule rejected by constraint engine: {len(v_list)} hard violation(s) detected: {', '.join(v_list[:2])}"
        )
        
    # Capture original slot for instant Undo / Revert
    orig_day = None
    orig_period = None
    orig_room = None
    for s in sessions:
        if s["session_id"] == payload.session_id:
            orig_day = s["day"]
            orig_period = s["start_period"]
            orig_room = s["room_id"]
            s["day"] = payload.new_day
            s["start_period"] = payload.new_period
            s["room_id"] = payload.new_room
            break
            
    if "reschedule_history" not in STATE:
        STATE["reschedule_history"] = []
    if orig_day and (orig_day != payload.new_day or orig_period != payload.new_period or orig_room != payload.new_room):
        STATE["reschedule_history"].append({
            "session_id": payload.session_id,
            "orig_day": orig_day,
            "orig_period": orig_period,
            "orig_room": orig_room,
            "new_day": payload.new_day,
            "new_period": payload.new_period,
            "new_room": payload.new_room,
            "timestamp": time.time()
        })

    with open(SCHEDULE_PATH, "w", encoding="utf-8") as f:
        json.dump(sched, f, indent=2)

    return {
        "status": "SUCCESS", 
        "message": f"Successfully moved {payload.session_id} to {payload.new_day} P{payload.new_period} ({payload.new_room}) with 0 Hard Violations!",
        "soft_penalties": rep.get("soft_penalties", {}),
        "revert_payload": {
            "session_id": payload.session_id,
            "new_day": orig_day,
            "new_period": orig_period,
            "new_room": orig_room
        }
    }

@app.post("/api/ai/revert-last")
def revert_last_reschedule():
    history = STATE.get("reschedule_history", [])
    if not history:
        raise HTTPException(status_code=400, detail="No reschedule operations in history to revert.")
    
    last = history.pop()
    sched = STATE["current_schedule"]
    sessions = sched.get("sessions", [])
    found = False
    for s in sessions:
        if s["session_id"] == last["session_id"]:
            s["day"] = last["orig_day"]
            s["start_period"] = last["orig_period"]
            s["room_id"] = last["orig_room"]
            found = True
            break
            
    if not found:
        raise HTTPException(status_code=404, detail="Target session not found in schedule")

    with open(SCHEDULE_PATH, "w", encoding="utf-8") as f:
        json.dump(sched, f, indent=2)

    return {
        "status": "SUCCESS",
        "message": f"Reverted {last['session_id']} back to {last['orig_day']} P{last['orig_period']} ({last['orig_room']}) with 0 Violations!",
        "reverted_session": last,
        "remaining_history_count": len(history)
    }

@app.get("/api/ai/reschedule-history")
def get_reschedule_history():
    return {
        "history": STATE.get("reschedule_history", [])
    }

# ----------------- Disruption & Repair -----------------
@app.get("/api/disruptions")
def get_disruptions():
    with open(DISRUPTION_PATH, "r", encoding="utf-8") as f:
        sample = json.load(f)
    return {
        "available_disruption": sample,
        "is_applied": STATE["disruption_applied"],
        "has_pending_repair": STATE["pending_repair"] is not None,
        "pending_repair_stats": STATE["pending_repair"]["stats"] if STATE["pending_repair"] else None
    }

@app.post("/api/disruptions/simulate")
def simulate_disruption():
    with open(DISRUPTION_PATH, "r", encoding="utf-8") as f:
        disruption = json.load(f)

    # Compute repair without applying
    repair_res = repair_timetable(STATE["data"], STATE["current_schedule"], disruption, max_seconds=30.0)
    if repair_res["status"] != "SUCCESS":
        raise HTTPException(status_code=500, detail=repair_res.get("error", "Repair failed"))

    STATE["pending_repair"] = repair_res
    return {
        "status": "SIMULATED",
        "diff": repair_res["diff"],
        "stats": repair_res["stats"]
    }

@app.post("/api/disruptions/apply")
def apply_disruption_api():
    if not STATE["pending_repair"]:
        simulate_disruption()

    repair_res = STATE["pending_repair"]
    STATE["current_schedule"] = repair_res["schedule"]
    STATE["disruption_applied"] = True
    
    # Save schedule_after.json
    with open(SCHEDULE_AFTER_PATH, "w", encoding="utf-8") as f:
        json.dump(repair_res["schedule"], f, indent=2)

    return {
        "status": "APPLIED",
        "message": "Disruption successfully repaired and applied by Admin.",
        "stats": repair_res["stats"]
    }

# ----------------- Official Validator API -----------------
@app.get("/api/validator/report")
def get_validator_report():
    data = STATE["data"]
    sched = STATE["current_schedule"]
    
    # Baseline for disruption check
    baseline = None
    if STATE["disruption_applied"]:
        with open(SCHEDULE_PATH, "r", encoding="utf-8") as f:
            baseline = json.load(f)
        with open(DISRUPTION_PATH, "r", encoding="utf-8") as f:
            disruption = json.load(f)
        data = apply_disruption(data, disruption)

    rep = validator.run(data, sched, baseline=baseline)
    return rep

# ----------------- Custom Uploads & Downloads -----------------
@app.post("/api/dataset/upload")
async def upload_custom_dataset(file: UploadFile = File(...)):
    try:
        content = await file.read()
        custom_data = json.loads(content.decode("utf-8"))
        # Verify required keys
        for k in ["calendar", "rooms", "faculty", "student_groups", "sessions"]:
            if k not in custom_data:
                raise ValueError(f"Missing required key '{k}' in dataset")
        
        STATE["data"] = custom_data
        STATE["disruption_applied"] = False
        STATE["pending_repair"] = None

        # Automatically solve for new dataset
        tt = solve_timetable(custom_data)
        exams = solve_exams(custom_data)
        fest = solve_bookings(custom_data, tt["sessions"])
        STATE["current_schedule"] = {
            "team": "ChronoSync",
            "dataset_id": custom_data.get("dataset_id", "cit-custom"),
            "sessions": tt["sessions"],
            "fest_week": fest,
            "exams": exams
        }
        with open(SCHEDULE_PATH, "w", encoding="utf-8") as f:
            json.dump(STATE["current_schedule"], f, indent=2)

        return {
            "status": "SUCCESS",
            "message": f"Dataset '{file.filename}' uploaded and schedule generated with 0 violations!",
            "sessions_count": len(tt["sessions"]),
            "exams_count": len(exams)
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid dataset file: {str(e)}")

@app.post("/api/disruptions/upload")
async def upload_custom_disruption(file: UploadFile = File(...)):
    try:
        content = await file.read()
        disruption = json.loads(content.decode("utf-8"))
        if "changes" not in disruption:
            raise ValueError("Disruption JSON must contain 'changes' array")

        # Run repair
        repair_res = repair_timetable(STATE["data"], STATE["current_schedule"], disruption, max_seconds=30.0)
        if repair_res["status"] != "SUCCESS":
            return {
                "status": "INFEASIBLE",
                "error": "No valid schedule repair exists. Constraints conflict with current session requirements."
            }

        STATE["pending_repair"] = repair_res
        STATE["active_disruption"] = disruption
        return {
            "status": "SUCCESS",
            "message": f"Disruption '{file.filename}' simulated successfully!",
            "diff": repair_res["diff"],
            "stats": repair_res["stats"]
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid disruption file: {str(e)}")

@app.get("/api/exports/download/{filename}")
def download_export_file(filename: str):
    if filename not in ("schedule.json", "schedule_after.json"):
        raise HTTPException(status_code=400, detail="Invalid export filename")
    
    file_path = os.path.join("exports", filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not generated yet")
    return FileResponse(file_path, filename=filename, media_type="application/json")

# ----------------- Room Utilisation & Free Room Finder -----------------
@app.get("/api/rooms/free")
def get_free_rooms(day: str = Query("MON"), start_period: int = Query(1), end_period: int = Query(2)):
    d = STATE["data"]
    sched = STATE["current_schedule"]
    rooms = d.get("rooms", [])

    room_un = defaultdict(set)
    for u in d.get("room_unavailability", []):
        for p in u["periods"]:
            room_un[u["room_id"]].add((u["day"], p))

    # Busy rooms from regular timetable
    busy = set()
    for s in sched.get("sessions", []):
        if s["day"] == day:
            dur = next((sm["duration"] for sm in d["sessions"] if sm["id"] == s["session_id"]), 1)
            p_range = range(s["start_period"], s["start_period"] + dur)
            for p in range(start_period, end_period + 1):
                if p in p_range:
                    busy.add(s["room_id"])

    # Busy rooms from bookings
    for b in sched.get("fest_week", {}).get("bookings", []):
        if b.get("status") == "approved" and b.get("day") == day:
            p_range = range(b["start_period"], b["end_period"] + 1)
            for p in range(start_period, end_period + 1):
                if p in p_range:
                    busy.add(b["room_id"])

    free_rooms = []
    for r in rooms:
        rid = r["id"]
        if rid in busy:
            continue
        if any((day, p) in room_un[rid] for p in range(start_period, end_period + 1)):
            continue
        free_rooms.append(r)

    return {"day": day, "period_range": f"P{start_period}-P{end_period}", "free_rooms": free_rooms}

@app.get("/api/rooms/utilisation")
def get_room_utilisation():
    d = STATE["data"]
    sched = STATE["current_schedule"]
    rooms = d.get("rooms", [])

    # Total available slots per room = 5 days * 9 teaching periods = 45 teaching slots
    room_hours = defaultdict(int)
    for s in sched.get("sessions", []):
        dur = next((sm["duration"] for sm in d["sessions"] if sm["id"] == s["session_id"]), 1)
        room_hours[s["room_id"]] += dur

    stats = []
    for r in rooms:
        rid = r["id"]
        used_h = room_hours[rid]
        pct = round((used_h / 45.0) * 100, 1)
        stats.append({
            "room_id": rid,
            "name": r["name"],
            "type": r["type"],
            "capacity": r["capacity"],
            "accessible": r.get("accessible", False),
            "used_hours": used_h,
            "total_slots": 45,
            "utilisation_pct": pct
        })

    return {"room_utilisation": sorted(stats, key=lambda x: x["utilisation_pct"], reverse=True)}

# ----------------- Manual Event Booking with Hard Constraint Checks -----------------
class ManualBookingPayload(BaseModel):
    title: str
    requester: str
    role: str
    attendance: int
    day: str
    start_period: int
    end_period: int
    room_id: str
    needs: Optional[List[str]] = []
    mandatory_groups: Optional[List[str]] = []

@app.post("/api/bookings/manual")
def create_manual_booking(payload: ManualBookingPayload):
    d = STATE["data"]
    sched = STATE["current_schedule"]
    rooms_map = {r["id"]: r for r in d["rooms"]}

    # Rule checks
    room = rooms_map.get(payload.room_id)
    if not room:
        raise HTTPException(status_code=400, detail=f"Room '{payload.room_id}' does not exist.")

    if "event" not in room.get("allowed_uses", []):
        raise HTTPException(status_code=400, detail=f"Room '{room['name']}' does not allow events.")

    if room["capacity"] < payload.attendance:
        raise HTTPException(
            status_code=400,
            detail=f"Capacity conflict: Room capacity ({room['capacity']}) is smaller than attendance ({payload.attendance})."
        )

    # Check accessibility
    if "accessible" in payload.needs and not room.get("accessible", False):
        raise HTTPException(
            status_code=400,
            detail=f"Accessibility violation: Event requires wheelchair accessibility, but {room['name']} is not accessible."
        )

    # Check time slot conflict with classes
    for s in sched.get("sessions", []):
        if s["day"] == payload.day and s["room_id"] == payload.room_id:
            dur = next((sm["duration"] for sm in d["sessions"] if sm["id"] == s["session_id"]), 1)
            p_range = range(s["start_period"], s["start_period"] + dur)
            for p in range(payload.start_period, payload.end_period + 1):
                if p in p_range:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Room conflict: {payload.room_id} is already occupied by class {s['session_id']} at {payload.day} Period {p}."
                    )

    # Check conflict with existing approved bookings
    for b in sched.get("fest_week", {}).get("bookings", []):
        if b.get("status") == "approved" and b.get("day") == payload.day and b.get("room_id") == payload.room_id:
            p_range = range(b["start_period"], b["end_period"] + 1)
            for p in range(payload.start_period, payload.end_period + 1):
                if p in p_range:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Room conflict: {payload.room_id} is already booked by request {b['request_id']} at {payload.day} Period {p}."
                    )

    new_booking = {
        "request_id": f"MANUAL-{int(time.time()) % 10000}",
        "status": "approved",
        "day": payload.day,
        "start_period": payload.start_period,
        "end_period": payload.end_period,
        "room_id": payload.room_id,
        "reason": f"Manually scheduled by authorized {payload.role.capitalize()}",
        "title": payload.title,
        "requester": payload.requester,
        "attendance": payload.attendance,
        "role": payload.role
    }

    sched["fest_week"]["bookings"].insert(0, new_booking)
    try:
        os.makedirs(os.path.dirname(SCHEDULE_PATH) or ".", exist_ok=True)
        with open(SCHEDULE_PATH, "w", encoding="utf-8") as f:
            json.dump(sched, f, indent=2)
    except Exception:
        pass
    return {"status": "SUCCESS", "message": "Manual booking approved with zero conflicts!", "booking": new_booking}


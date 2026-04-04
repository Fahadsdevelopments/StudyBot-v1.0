from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from bson import ObjectId
import shutil
import os
from datetime import datetime, timedelta
from collections import defaultdict
from processor import process_pdf
from pymongo import MongoClient
from pymongo.server_api import ServerApi
from dotenv import load_dotenv
import uuid

load_dotenv()

app = FastAPI(title="Student AI Assistant Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── MongoDB ────────────────────────────────────────────────────
def get_mongo_client():
    uri = os.getenv("MONGODB_URI")
    return MongoClient(
        uri, server_api=ServerApi('1'),
        tls=True, tlsAllowInvalidCertificates=True,
        tlsAllowInvalidHostnames=True,
        serverSelectionTimeoutMS=30000,
        connectTimeoutMS=30000,
        socketTimeoutMS=30000,
    )

client = get_mongo_client()
db = client["studybot"]

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ── XP config ──────────────────────────────────────────────────
XP_PER_TASK = 50
XP_PER_HOUR = 20
XP_BEAT_ESTIMATE_BONUS = 30
XP_PERFECT_ESTIMATE_BONUS = 15

LEVEL_THRESHOLDS = [0,100,250,500,900,1400,2000,2800,3800,5000,6500,8500,11000,14000,18000]
LEVEL_NAMES = ["Beginner","Novice","Apprentice","Student","Learner","Scholar",
               "Adept","Expert","Master","Grandmaster","Sage","Legend",
               "Mythic","Transcendent","Omniscient"]

def get_level(xp):
    for i in range(len(LEVEL_THRESHOLDS)-1, -1, -1):
        if xp >= LEVEL_THRESHOLDS[i]:
            return i, LEVEL_NAMES[i]
    return 0, LEVEL_NAMES[0]

def xp_to_next_level(xp):
    level, _ = get_level(xp)
    if level >= len(LEVEL_THRESHOLDS)-1:
        return 0
    return LEVEL_THRESHOLDS[level+1] - xp

def award_xp(user_id, course_code, xp_amount, reason):
    profile = db["xp_profiles"].find_one({"user_id": user_id, "course_code": course_code})
    if profile:
        new_xp = profile["xp"] + xp_amount
        old_level, _ = get_level(profile["xp"])
        new_level, new_level_name = get_level(new_xp)
        db["xp_profiles"].update_one(
            {"_id": profile["_id"]},
            {"$set": {"xp": new_xp, "updated_at": datetime.utcnow()},
             "$push": {"history": {"xp": xp_amount, "reason": reason, "at": datetime.utcnow()}}}
        )
        leveled_up = new_level > old_level
        return new_xp, new_level, new_level_name, leveled_up
    else:
        new_level, new_level_name = get_level(xp_amount)
        db["xp_profiles"].insert_one({
            "user_id": user_id,
            "course_code": course_code or "GENERAL",
            "xp": xp_amount,
            "history": [{"xp": xp_amount, "reason": reason, "at": datetime.utcnow()}],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        })
        return xp_amount, new_level, new_level_name, new_level > 0


# ══════════════════════════════════════════════════════════════
# UPLOAD
# ══════════════════════════════════════════════════════════════
@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...),
                     doc_type: str = "assignment",
                     course_code: str = None):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    unique_filename = f"{uuid.uuid4()}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        result = process_pdf(file_path, file.filename, doc_type, course_code)
        return JSONResponse(content={
            "success": True,
            "message": f"Successfully processed {file.filename}",
            "doc_id": result["doc_id"],
            "filename": file.filename,
            "doc_type": doc_type,
            "summary": result["summary"],
            "topics": result["topics"],
            "tasks_found": result["tasks_found"],
            "tasks": result["tasks"],
            "processed_at": datetime.utcnow().isoformat()
        })
    except Exception as e:
        print(f"Error processing {file.filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process document: {str(e)}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


# ══════════════════════════════════════════════════════════════
# TASKS
# ══════════════════════════════════════════════════════════════
@app.get("/tasks")
async def get_tasks(limit: int = 20):
    tasks = list(db["tasks"].find({}, {"_id": 0}).sort("created_at", -1).limit(limit))
    for t in tasks:
        for k, v in t.items():
            if isinstance(v, datetime): t[k] = v.isoformat()
    return {"success": True, "count": len(tasks), "tasks": tasks}

@app.get("/tasks/pending")
async def get_pending_tasks():
    tasks = list(db["tasks"].find({"status": "pending"}, {"_id": 0}).sort("priority", -1))
    for t in tasks:
        for k, v in t.items():
            if isinstance(v, datetime): t[k] = v.isoformat()
    return {"success": True, "count": len(tasks), "tasks": tasks}

@app.get("/tasks/doc/{doc_id}")
async def get_tasks_by_doc(doc_id: str):
    tasks = list(db["tasks"].find({"doc_id": doc_id}, {"_id": 0}).sort("created_at", -1))
    for t in tasks:
        for k, v in t.items():
            if isinstance(v, datetime): t[k] = v.isoformat()
    return {"success": True, "doc_id": doc_id, "count": len(tasks), "tasks": tasks}

@app.post("/tasks/adjust-time")
async def adjust_task_time(data: dict):
    multiplier = data.get("multiplier", 1.0)
    doc_id = data.get("doc_id")
    query = {"status": "pending"}
    if doc_id: query["doc_id"] = doc_id
    tasks = list(db["tasks"].find(query, {"_id": 1, "estimated_hours": 1}).limit(10))
    for task in tasks:
        new_hours = max(0.5, round(task["estimated_hours"] * multiplier, 1))
        db["tasks"].update_one({"_id": task["_id"]}, {"$set": {"estimated_hours": new_hours}})
    return {"success": True, "adjusted": len(tasks), "multiplier": multiplier}

@app.delete("/tasks/clear-all")
async def clear_all_tasks():
    result = db["tasks"].delete_many({})
    return {"success": True, "deleted": result.deleted_count}

@app.post("/tasks/{task_id}/complete")
async def complete_task(task_id: str):
    try: object_id = ObjectId(task_id)
    except: raise HTTPException(status_code=400, detail="Invalid task ID")
    result = db["tasks"].update_one(
        {"_id": object_id},
        {"$set": {"status": "completed", "updated_at": datetime.utcnow()}}
    )
    if result.modified_count == 1:
        return {"success": True, "message": "Task marked as completed"}
    raise HTTPException(status_code=404, detail="Task not found")

@app.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    try: object_id = ObjectId(task_id)
    except: raise HTTPException(status_code=400, detail="Invalid task ID")
    result = db["tasks"].delete_one({"_id": object_id})
    if result.deleted_count == 1:
        return {"success": True, "message": "Task deleted"}
    raise HTTPException(status_code=404, detail="Task not found")


# ══════════════════════════════════════════════════════════════
# DOCUMENTS
# ══════════════════════════════════════════════════════════════
@app.get("/documents")
async def get_documents(limit: int = 20):
    docs = list(db["documents"].find({}, {"_id": 0}).sort("uploaded_at", -1).limit(limit))
    for d in docs:
        for k, v in d.items():
            if isinstance(v, datetime): d[k] = v.isoformat()
    return {"success": True, "count": len(docs), "documents": docs}

@app.get("/documents/type/{doc_type}")
async def get_documents_by_type(doc_type: str, limit: int = 20):
    docs = list(db["documents"].find({"doc_type": doc_type}, {"_id": 0}).sort("uploaded_at", -1).limit(limit))
    for d in docs:
        for k, v in d.items():
            if isinstance(v, datetime): d[k] = v.isoformat()
    return {"success": True, "count": len(docs), "documents": docs}


# ══════════════════════════════════════════════════════════════
# SUBJECTS
# ══════════════════════════════════════════════════════════════
@app.get("/subjects")
async def get_subjects():
    subjects = list(db["subjects"].find({}, {"_id": 0}))
    return {"success": True, "subjects": subjects}

@app.post("/subjects")
async def add_subject(data: dict):
    code = data.get("code", "").upper().strip()
    name = data.get("name", "").strip()
    ects = data.get("ects", 0)
    if not code or not name:
        raise HTTPException(status_code=400, detail="Code and name required")
    if db["subjects"].find_one({"code": code}):
        raise HTTPException(status_code=400, detail=f"Subject {code} already exists")
    db["subjects"].insert_one({"code": code, "name": name, "ects": ects, "created_at": datetime.utcnow()})
    return {"success": True, "code": code, "name": name, "ects": ects}

@app.delete("/subjects/{code}")
async def remove_subject(code: str):
    code = code.upper()
    result = db["subjects"].delete_one({"code": code})
    if result.deleted_count == 1:
        return {"success": True, "message": f"Removed {code}"}
    raise HTTPException(status_code=404, detail=f"Subject {code} not found")

@app.get("/subjects/{code}/tasks")
async def get_tasks_by_subject(code: str):
    code = code.upper()
    subject = db["subjects"].find_one({"code": code}, {"_id": 0})
    if not subject:
        raise HTTPException(status_code=404, detail=f"Subject {code} not found")
    tasks = list(db["tasks"].find({"course_code": code, "status": "pending"}, {"_id": 0}).sort("priority", -1))
    for t in tasks:
        for k, v in t.items():
            if isinstance(v, datetime): t[k] = v.isoformat()
    return {"success": True, "subject": subject["name"], "code": code, "count": len(tasks), "tasks": tasks}

@app.get("/subjects/{code}/docs")
async def get_docs_by_subject(code: str):
    code = code.upper()
    subject = db["subjects"].find_one({"code": code}, {"_id": 0})
    if not subject:
        raise HTTPException(status_code=404, detail=f"Subject {code} not found")
    docs = list(db["documents"].find({"course_code": code}, {"_id": 0}).sort("uploaded_at", -1))
    for d in docs:
        for k, v in d.items():
            if isinstance(v, datetime): d[k] = v.isoformat()
    return {"success": True, "subject": subject["name"], "code": code, "count": len(docs), "documents": docs}


# ══════════════════════════════════════════════════════════════
# HEALTH & SCHEDULE
# ══════════════════════════════════════════════════════════════
@app.get("/health")
async def health():
    try:
        client.admin.command("ping")
        db_status = "connected"
    except Exception as e:
        db_status = f"disconnected: {str(e)[:50]}"
    return {"status": "ok", "db": db_status, "timestamp": datetime.utcnow().isoformat(), "version": "2.0"}

@app.get("/schedule")
async def generate_schedule(hours_available: int = 6):
    # Get protected blocks for today
    today = datetime.utcnow().strftime('%A')  # e.g. "Monday"
    protected = list(db["protected_blocks"].find({
        "$or": [{"day": today}, {"day": "daily"}]
    }))
    protected_ranges = [(b["start_time"], b["end_time"]) for b in protected]

    tasks = list(db["tasks"].find({"status": "pending"}, {"_id": 0}).sort("priority", -1).limit(10))
    if not tasks:
        return {"success": True, "message": "No pending tasks to schedule", "schedule": []}

    for t in tasks:
        for k, v in t.items():
            if isinstance(v, datetime): t[k] = v.isoformat()

    schedule = []
    hours_used = 0
    current_hour = 9

    def is_protected(hour):
        for start, end in protected_ranges:
            s = int(start.split(':')[0])
            e = int(end.split(':')[0])
            if s <= hour < e:
                return True
        return False

    for task in tasks:
        if hours_used >= hours_available:
            break
        # Skip protected hours
        while is_protected(current_hour) and current_hour < 22:
            current_hour += 1

        session_hours = min(task.get("estimated_hours", 2), 2)
        if hours_used + session_hours > hours_available:
            session_hours = hours_available - hours_used
        if session_hours <= 0:
            break

        schedule.append({
            "title": task.get("title", "Study Session"),
            "type": task.get("type", "other"),
            "complexity": task.get("complexity", "medium"),
            "course_code": task.get("course_code", ""),
            "start_time": f"{current_hour:02d}:00",
            "end_time": f"{current_hour + session_hours:02d}:00",
            "duration_hours": session_hours,
            "due_date": task.get("due_date"),
            "doc_id": task.get("doc_id")
        })

        hours_used += session_hours
        current_hour += session_hours
        if hours_used % 2 == 0 and hours_used < hours_available:
            current_hour += 1

    return {
        "success": True,
        "hours_available": hours_available,
        "hours_scheduled": hours_used,
        "block_count": len(schedule),
        "protected_blocks": len(protected_ranges),
        "schedule": schedule
    }

@app.post("/schedule/sync-calendar")
async def sync_schedule_to_calendar(hours_available: int = 6):
    try:
        from calendar_sync import push_schedule_to_calendar
        schedule_res = await generate_schedule(hours_available)
        if not schedule_res["schedule"]:
            return {"success": False, "message": "No pending tasks to schedule"}
        links = push_schedule_to_calendar(schedule_res["schedule"])
        return {"success": True, "message": f"Pushed {len(links)} events", "events": links}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════
# SESSIONS & SKILLS
# ══════════════════════════════════════════════════════════════
@app.post("/sessions/start")
async def start_session(data: dict):
    user_id = data.get("user_id")
    task_title = data.get("task_title")
    task = db["tasks"].find_one(
        {"title": {"$regex": task_title, "$options": "i"}, "status": "pending"},
        {"_id": 1, "title": 1, "estimated_hours": 1, "topics": 1, "complexity": 1, "course_code": 1}
    )
    if not task:
        return {"success": False, "message": "Task not found"}
    db["sessions"].update_many(
        {"user_id": user_id, "end_time": None},
        {"$set": {"end_time": datetime.utcnow(), "abandoned": True}}
    )
    session = {
        "user_id": user_id,
        "task_id": str(task["_id"]),
        "task_title": task["title"],
        "estimated_hours": task.get("estimated_hours", 1),
        "topics": task.get("topics", []),
        "complexity": task.get("complexity", "medium"),
        "course_code": task.get("course_code", "GENERAL"),
        "start_time": datetime.utcnow(),
        "end_time": None,
        "actual_hours": None,
        "abandoned": False
    }
    db["sessions"].insert_one(session)
    return {"success": True, "task_title": task["title"], "estimated_hours": task.get("estimated_hours", 1)}

@app.post("/sessions/stop")
async def stop_session(data: dict):
    user_id = data.get("user_id")
    session = db["sessions"].find_one({"user_id": user_id, "end_time": None})
    if not session:
        return {"success": False, "message": "No active session found"}

    end_time = datetime.utcnow()
    actual_hours = round((end_time - session["start_time"]).total_seconds() / 3600, 2)

    db["sessions"].update_one(
        {"_id": session["_id"]},
        {"$set": {"end_time": end_time, "actual_hours": actual_hours}}
    )
    db["tasks"].update_one(
        {"_id": ObjectId(session["task_id"])},
        {"$set": {"status": "completed", "actual_hours": actual_hours}}
    )

    estimated = session.get("estimated_hours", 1)
    ratio = actual_hours / max(estimated, 0.1)

    # Update skill profiles
    for topic in session.get("topics", []):
        existing = db["skill_profiles"].find_one({"user_id": user_id, "topic": topic})
        if existing:
            history = existing.get("ratios", [])
            history.append(ratio)
            history = history[-5:]
            db["skill_profiles"].update_one(
                {"_id": existing["_id"]},
                {"$set": {"ratios": history, "avg_ratio": sum(history)/len(history),
                          "sessions_count": existing.get("sessions_count", 0) + 1,
                          "last_updated": datetime.utcnow()}}
            )
        else:
            db["skill_profiles"].insert_one({
                "user_id": user_id, "topic": topic,
                "ratios": [ratio], "avg_ratio": ratio,
                "sessions_count": 1, "last_updated": datetime.utcnow()
            })

    # Award XP
    course_code = session.get("course_code", "GENERAL")
    xp_earned = XP_PER_TASK + int(actual_hours * XP_PER_HOUR)
    xp_reason = f"Completed: {session['task_title']}"
    if ratio < 0.7:
        xp_earned += XP_BEAT_ESTIMATE_BONUS
        xp_reason += " + beat estimate bonus"
    elif ratio < 1.3:
        xp_earned += XP_PERFECT_ESTIMATE_BONUS
        xp_reason += " + accurate estimate bonus"

    new_xp, level, level_name, leveled_up = award_xp(user_id, course_code, xp_earned, xp_reason)

    if ratio < 0.3:
        feedback = "⚡ Way faster than expected! You clearly know this well."
        skill_change = "📈 Skill updated — future estimates will be shorter."
    elif ratio < 0.7:
        feedback = "🚀 Faster than estimated! Good work."
        skill_change = "📈 Estimates adjusted down slightly."
    elif ratio < 1.3:
        feedback = "✅ Right on track with the estimate."
        skill_change = "📊 Estimate was accurate — no change needed."
    elif ratio < 2.0:
        feedback = "🐢 Took a bit longer than expected."
        skill_change = "📉 Future estimates for this topic will be higher."
    else:
        feedback = "💪 This one was tough!"
        skill_change = "📉 Skill updated — future estimates will be longer."

    return {
        "success": True,
        "task_title": session["task_title"],
        "estimated_hours": estimated,
        "actual_hours": actual_hours,
        "ratio": ratio,
        "feedback": feedback,
        "skill_change": skill_change,
        "topics": session.get("topics", []),
        "xp_earned": xp_earned,
        "total_xp": new_xp,
        "level": level,
        "level_name": level_name,
        "leveled_up": leveled_up,
        "xp_to_next": xp_to_next_level(new_xp)
    }

@app.get("/skills")
async def get_skill_profile(user_id: str):
    skills = list(db["skill_profiles"].find({"user_id": user_id}, {"_id": 0}).sort("sessions_count", -1))
    for s in skills:
        if isinstance(s.get("last_updated"), datetime):
            s["last_updated"] = s["last_updated"].isoformat()
        avg = s.get("avg_ratio", 1.0)
        s["level"] = "Expert ⚡" if avg < 0.5 else "Strong 💪" if avg < 0.8 else "On track ✅" if avg < 1.2 else "Developing 📚" if avg < 1.8 else "Needs work 🔧"
    return {"success": True, "skills": skills}


# ══════════════════════════════════════════════════════════════
# GAMIFICATION
# ══════════════════════════════════════════════════════════════
@app.get("/xp")
async def get_xp_profile(user_id: str):
    profiles = list(db["xp_profiles"].find({"user_id": user_id}, {"_id": 0, "history": 0}))
    result = []
    for p in profiles:
        xp = p.get("xp", 0)
        level, level_name = get_level(xp)
        result.append({
            "course_code": p["course_code"],
            "xp": xp,
            "level": level,
            "level_name": level_name,
            "xp_to_next": xp_to_next_level(xp)
        })
    result.sort(key=lambda x: x["xp"], reverse=True)
    return {"success": True, "profiles": result}


# ══════════════════════════════════════════════════════════════
# EXAM TRACKER
# ══════════════════════════════════════════════════════════════
@app.post("/exams")
async def add_exam(data: dict):
    course_code = data.get("course_code", "").upper()
    exam_date = data.get("exam_date")
    exam_time = data.get("exam_time", "")
    location = data.get("location", "")
    notes = data.get("notes", "")

    if not course_code or not exam_date:
        raise HTTPException(status_code=400, detail="course_code and exam_date required")

    # Parse date
    try:
        parsed_date = datetime.strptime(exam_date, "%Y-%m-%d")
    except:
        raise HTTPException(status_code=400, detail="Date must be YYYY-MM-DD format")

    # Remove existing exam for this subject if any
    db["exams"].delete_one({"course_code": course_code})

    db["exams"].insert_one({
        "course_code": course_code,
        "exam_date": parsed_date,
        "exam_time": exam_time,
        "location": location,
        "notes": notes,
        "created_at": datetime.utcnow()
    })

    subject = db["subjects"].find_one({"code": course_code}, {"_id": 0, "name": 1})
    subject_name = subject["name"] if subject else course_code

    days_until = (parsed_date - datetime.utcnow()).days

    return {
        "success": True,
        "course_code": course_code,
        "subject_name": subject_name,
        "exam_date": exam_date,
        "exam_time": exam_time,
        "location": location,
        "days_until": days_until
    }

@app.get("/exams")
async def get_exams():
    exams = list(db["exams"].find({}, {"_id": 0}).sort("exam_date", 1))
    now = datetime.utcnow()
    result = []
    for e in exams:
        exam_date = e.get("exam_date")
        if isinstance(exam_date, datetime):
            days_until = (exam_date - now).days
            e["exam_date"] = exam_date.strftime("%Y-%m-%d")
            e["days_until"] = days_until
            e["urgency"] = "🔴 THIS WEEK" if days_until <= 7 else "🟡 SOON" if days_until <= 21 else "🟢 UPCOMING"
            subject = db["subjects"].find_one({"code": e["course_code"]}, {"_id": 0, "name": 1})
            e["subject_name"] = subject["name"] if subject else e["course_code"]
            result.append(e)
    return {"success": True, "exams": result}

@app.delete("/exams/{course_code}")
async def delete_exam(course_code: str):
    result = db["exams"].delete_one({"course_code": course_code.upper()})
    if result.deleted_count == 1:
        return {"success": True, "message": f"Exam for {course_code} removed"}
    raise HTTPException(status_code=404, detail="Exam not found")


# ══════════════════════════════════════════════════════════════
# GRADES & ECTS
# ══════════════════════════════════════════════════════════════
@app.post("/grades")
async def add_grade(data: dict):
    course_code = data.get("course_code", "").upper()
    grade = data.get("grade")
    assessment = data.get("assessment", "final")  # final, midterm, assignment

    if not course_code or grade is None:
        raise HTTPException(status_code=400, detail="course_code and grade required")

    try:
        grade = float(grade)
    except:
        raise HTTPException(status_code=400, detail="Grade must be a number")

    if not (1.0 <= grade <= 5.0):
        raise HTTPException(status_code=400, detail="Grade must be between 1.0 and 5.0")

    subject = db["subjects"].find_one({"code": course_code}, {"_id": 0})
    if not subject:
        raise HTTPException(status_code=404, detail=f"Subject {course_code} not found")

    ects = subject.get("ects", 0)

    # Check if grade for this assessment already exists
    db["grades"].update_one(
        {"course_code": course_code, "assessment": assessment},
        {"$set": {
            "course_code": course_code,
            "subject_name": subject["name"],
            "grade": grade,
            "ects": ects,
            "assessment": assessment,
            "passed": grade <= 4.0,
            "updated_at": datetime.utcnow()
        }},
        upsert=True
    )

    grade_label = "1.0 (Sehr Gut)" if grade <= 1.3 else \
                  "2.0 (Gut)" if grade <= 2.3 else \
                  "3.0 (Befriedigend)" if grade <= 3.3 else \
                  "4.0 (Ausreichend)" if grade <= 4.0 else "5.0 (Nicht Bestanden)"

    return {
        "success": True,
        "course_code": course_code,
        "subject_name": subject["name"],
        "grade": grade,
        "grade_label": grade_label,
        "ects": ects,
        "passed": grade <= 4.0
    }

@app.get("/grades")
async def get_grades():
    grades = list(db["grades"].find({}, {"_id": 0}))
    for g in grades:
        if isinstance(g.get("updated_at"), datetime):
            g["updated_at"] = g["updated_at"].isoformat()

    # Calculate GPA (weighted by ECTS)
    final_grades = [g for g in grades if g.get("assessment") == "final" and g.get("passed")]
    total_ects = sum(g.get("ects", 0) for g in final_grades)
    weighted_sum = sum(g["grade"] * g.get("ects", 0) for g in final_grades)
    gpa = round(weighted_sum / total_ects, 2) if total_ects > 0 else None

    # Total ECTS from all subjects
    all_subjects = list(db["subjects"].find({}, {"_id": 0, "ects": 1}))
    total_possible_ects = sum(s.get("ects", 0) for s in all_subjects)

    return {
        "success": True,
        "grades": grades,
        "gpa": gpa,
        "ects_earned": total_ects,
        "ects_total": total_possible_ects
    }


# ══════════════════════════════════════════════════════════════
# PROTECTED TIME BLOCKS
# ══════════════════════════════════════════════════════════════
@app.post("/protected")
async def add_protected_block(data: dict):
    day = data.get("day", "").capitalize()
    start_time = data.get("start_time")
    end_time = data.get("end_time")
    label = data.get("label", "Personal time")

    valid_days = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday","daily"]
    if day not in valid_days:
        raise HTTPException(status_code=400, detail=f"Day must be one of: {', '.join(valid_days)}")
    if not start_time or not end_time:
        raise HTTPException(status_code=400, detail="start_time and end_time required (HH:MM)")

    db["protected_blocks"].insert_one({
        "day": day,
        "start_time": start_time,
        "end_time": end_time,
        "label": label,
        "created_at": datetime.utcnow()
    })
    return {"success": True, "day": day, "start_time": start_time, "end_time": end_time, "label": label}

@app.get("/protected")
async def get_protected_blocks():
    blocks = list(db["protected_blocks"].find({}, {"_id": 0, "created_at": 0}))
    return {"success": True, "blocks": blocks}

@app.delete("/protected")
async def remove_protected_block(data: dict):
    day = data.get("day", "").capitalize()
    start_time = data.get("start_time")
    result = db["protected_blocks"].delete_one({"day": day, "start_time": start_time})
    if result.deleted_count == 1:
        return {"success": True, "message": "Protected block removed"}
    raise HTTPException(status_code=404, detail="Block not found")


# ══════════════════════════════════════════════════════════════
# ANALYTICS
# ══════════════════════════════════════════════════════════════
@app.get("/analytics")
async def get_analytics(user_id: str, days: int = 30):
    since = datetime.utcnow() - timedelta(days=days)

    # Completed sessions in period
    sessions = list(db["sessions"].find({
        "user_id": user_id,
        "end_time": {"$gte": since},
        "actual_hours": {"$ne": None},
        "abandoned": {"$ne": True}
    }))

    # Study time per subject
    subject_hours = defaultdict(float)
    daily_hours = defaultdict(float)
    topic_sessions = defaultdict(list)

    for s in sessions:
        code = s.get("course_code", "GENERAL")
        hours = s.get("actual_hours", 0)
        subject_hours[code] += hours
        day_key = s["end_time"].strftime("%Y-%m-%d") if isinstance(s["end_time"], datetime) else "unknown"
        daily_hours[day_key] += hours
        for topic in s.get("topics", []):
            topic_sessions[topic].append(s.get("actual_hours", 0) / max(s.get("estimated_hours", 1), 0.1))

    # Mastery curves per topic
    mastery = {}
    for topic, ratios in topic_sessions.items():
        trend = "improving" if len(ratios) > 1 and ratios[-1] < ratios[0] else "stable"
        mastery[topic] = {
            "sessions": len(ratios),
            "avg_ratio": round(sum(ratios) / len(ratios), 2),
            "trend": trend,
            "level": "Expert ⚡" if sum(ratios)/len(ratios) < 0.5 else
                     "Strong 💪" if sum(ratios)/len(ratios) < 0.8 else
                     "On track ✅" if sum(ratios)/len(ratios) < 1.2 else
                     "Developing 📚" if sum(ratios)/len(ratios) < 1.8 else "Needs work 🔧"
        }

    # Best study days
    sorted_days = sorted(daily_hours.items(), key=lambda x: x[1], reverse=True)
    best_days = sorted_days[:5]

    total_hours = sum(subject_hours.values())
    tasks_completed = len(sessions)

    return {
        "success": True,
        "period_days": days,
        "total_hours": round(total_hours, 1),
        "tasks_completed": tasks_completed,
        "subject_breakdown": dict(subject_hours),
        "daily_hours": dict(daily_hours),
        "best_study_days": best_days,
        "mastery_curves": mastery
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

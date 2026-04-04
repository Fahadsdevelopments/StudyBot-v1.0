import fitz  # PyMuPDF
import json
import httpx
from datetime import datetime
from dateutil import parser as date_parser
from pymongo import MongoClient
from pymongo.server_api import ServerApi
from dotenv import load_dotenv
import os
import time

load_dotenv()

# ── MongoDB connection ─────────────────────────────────────────
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
tasks_collection = db["tasks"]
docs_collection  = db["documents"]

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

CHUNK_SIZE = 8000   # characters per Nemotron call
CHUNK_OVERLAP = 400 # overlap between chunks


# ── Text extraction ────────────────────────────────────────────
def extract_text_from_pdf(pdf_path: str) -> str:
    doc = fitz.open(pdf_path)
    full_text = ""
    for page in doc:
        full_text += page.get_text("text") + "\n"
    doc.close()
    return full_text.strip()


# ── Date parsing ───────────────────────────────────────────────
def parse_date_flexible(date_str: str):
    if not date_str:
        return None
    if str(date_str).lower() in ["null", "none", "tbd", "asap", "n/a", ""]:
        return None
    try:
        return date_parser.parse(str(date_str), fuzzy=True).isoformat()
    except Exception:
        return None


# ── Course context from MongoDB ────────────────────────────────
def get_course_context(course_code: str) -> dict:
    if not course_code:
        return {"slides_context": "", "past_paper_context": ""}

    slides = list(db["documents"].find(
        {"doc_type": "lecture_slides", "course_code": course_code},
        {"topics": 1, "summary": 1, "filename": 1, "_id": 0}
    ).limit(5))

    past_papers = list(db["documents"].find(
        {"doc_type": "past_paper", "course_code": course_code},
        {"topics": 1, "summary": 1, "filename": 1, "_id": 0}
    ).limit(5))

    slides_context = ""
    if slides:
        slides_context = "Lecture slide topics covered:\n"
        for s in slides:
            slides_context += f"- {s['filename']}: {', '.join(s.get('topics', []))}\n"

    past_paper_context = ""
    if past_papers:
        past_paper_context = "Topics from past exam papers:\n"
        for p in past_papers:
            past_paper_context += f"- {p['filename']}: {', '.join(p.get('topics', []))}\n"

    return {"slides_context": slides_context, "past_paper_context": past_paper_context}


# ── Prompt builder ─────────────────────────────────────────────
def build_prompt(text: str, filename: str, doc_type: str,
                 course_code: str = None, chunk_info: str = "") -> str:

    context = get_course_context(course_code)
    context_section = ""
    if context["slides_context"] or context["past_paper_context"]:
        context_section = f"""
Additional context for this course:
{context['slides_context']}
{context['past_paper_context']}
Use this context to better estimate complexity and time.
"""

    chunk_note = f"\n_Note: {chunk_info}_\n" if chunk_info else ""

    if doc_type == "assignment":
        return f"""You are analyzing a university assignment titled "{filename}".{chunk_note}
{context_section}
Extract ALL tasks, problems, and exercises.

Return ONLY valid JSON, no extra text:

{{
  "summary": "One sentence describing this assignment",
  "topics": ["topic1", "topic2"],
  "tasks": [
    {{
      "title": "Problem/task name",
      "due_date": null,
      "estimated_hours": 1,
      "type": "assignment",
      "priority": 75,
      "complexity": "low or medium or high"
    }}
  ]
}}

Rules for estimated_hours:
- Simple recall or definition: 0.5h
- Multi-step calculation or analysis: 1-2h
- Proof or novel problem: 2-3h
- Complex design or research: 3-5h
- Never exceed 6h per individual task
- complexity: low=recall, medium=application, high=proof/synthesis

Document content:
{text}"""

    elif doc_type == "lecture_slides":
        return f"""You are analyzing lecture slides titled "{filename}".{chunk_note}

Extract the main concepts and topics covered in this section.

Return ONLY valid JSON:

{{
  "summary": "One sentence describing what this section covers",
  "topics": ["topic1", "topic2", "topic3"],
  "key_concepts": ["concept1", "concept2"],
  "tasks": []
}}

Document content:
{text}"""

    elif doc_type == "past_paper":
        return f"""You are analyzing a past exam paper titled "{filename}".{chunk_note}

Extract topics tested and question patterns.

Return ONLY valid JSON:

{{
  "summary": "One sentence describing this exam section",
  "topics": ["topic1", "topic2"],
  "question_types": ["proof", "calculation", "definition"],
  "high_frequency_topics": ["most common topic"],
  "tasks": []
}}

Document content:
{text}"""

    else:
        return f"""You are analyzing a university document titled "{filename}".{chunk_note}

Return ONLY valid JSON:

{{
  "summary": "One sentence summary",
  "topics": ["topic1", "topic2"],
  "tasks": []
}}

Document content:
{text}"""


# ── Single Nemotron call ───────────────────────────────────────
def call_nemotron(prompt: str) -> dict:
    try:
        response = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost",
                "X-Title": "Student AI Assistant"
            },
            json={
                "model": "nvidia/nemotron-3-super-120b-a12b:free",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 2000,
                "temperature": 0.2
            },
            timeout=90
        )

        response_json = response.json()

        if "choices" not in response_json:
            print(f"[processor] No choices in response: {response_json}")
            return _empty_analysis()

        raw = response_json["choices"][0]["message"]["content"]
        start = raw.find("{")
        end   = raw.rfind("}") + 1

        if start == -1 or end == 0:
            print("[processor] No JSON in response")
            return _empty_analysis()

        analysis = json.loads(raw[start:end])

        # Normalise task fields
        for task in analysis.get("tasks", []):
            task["due_date"]        = parse_date_flexible(task.get("due_date"))
            task["estimated_hours"] = float(task.get("estimated_hours") or 1)
            task["priority"]        = int(task.get("priority") or 70)

            if task.get("type") not in {"assignment","exam","quiz","reading","project","lab","other"}:
                task["type"] = "other"
            if task.get("complexity") not in {"low","medium","high"}:
                task["complexity"] = "medium"

        return analysis

    except json.JSONDecodeError as e:
        print(f"[processor] JSON parse error: {e}")
        return _empty_analysis()
    except Exception as e:
        print(f"[processor] Nemotron error: {e}")
        return _empty_analysis()


# ── Chunked analysis for large documents ──────────────────────
def analyze_document(text: str, filename: str, doc_type: str,
                     course_code: str = None) -> dict:

    # Short document — single call
    if len(text) <= CHUNK_SIZE:
        print(f"[processor] Single call ({len(text)} chars)")
        prompt = build_prompt(text, filename, doc_type, course_code)
        return call_nemotron(prompt)

    # Large document — split into chunks
    chunks = []
    start  = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunks.append(text[start:end])
        start += CHUNK_SIZE - CHUNK_OVERLAP

    total_chunks = len(chunks)
    print(f"[processor] Chunking: {len(text)} chars → {total_chunks} chunks")

    all_tasks    = []
    all_topics   = set()
    all_concepts = []
    summaries    = []

    for i, chunk in enumerate(chunks):
        print(f"[processor] Chunk {i+1}/{total_chunks}")
        chunk_info = f"This is part {i+1} of {total_chunks} of the document."
        prompt = build_prompt(chunk, filename, doc_type, course_code, chunk_info)
        result = call_nemotron(prompt)

        all_tasks.extend(result.get("tasks", []))
        all_topics.update(result.get("topics", []))
        all_concepts.extend(result.get("key_concepts", []))

        if result.get("summary") and "Could not" not in result["summary"]:
            summaries.append(result["summary"])

        # Small delay between chunks to avoid rate limiting
        if i < total_chunks - 1:
            time.sleep(1)

    # Deduplicate tasks by title
    seen    = set()
    unique_tasks = []
    for task in all_tasks:
        key = task["title"].lower().strip()[:40]
        if key not in seen:
            seen.add(key)
            unique_tasks.append(task)

    # Build combined summary
    if summaries:
        final_summary = summaries[0]
        if total_chunks > 1:
            final_summary += f" (Analyzed across {total_chunks} sections)"
    else:
        final_summary = "Document analyzed automatically."

    return {
        "summary":              final_summary,
        "topics":               list(all_topics),
        "key_concepts":         list(set(all_concepts)),
        "tasks":                unique_tasks,
        "question_types":       [],
        "high_frequency_topics": []
    }


def _empty_analysis() -> dict:
    return {"summary": "Could not analyze document automatically.",
            "topics": [], "tasks": []}


# ── Save to MongoDB ────────────────────────────────────────────
def save_to_mongodb(filename: str, analysis: dict,
                    doc_type: str = "assignment",
                    course_code: str = None) -> tuple:

    doc_record = {
        "filename":   filename,
        "doc_type":   doc_type,
        "course_code": course_code,
        "topics":     analysis.get("topics", []),
        "summary":    analysis.get("summary", ""),
        "task_count": len(analysis.get("tasks", [])),
        "uploaded_at": datetime.utcnow()
    }

    if doc_type == "lecture_slides":
        doc_record["key_concepts"] = analysis.get("key_concepts", [])
    elif doc_type == "past_paper":
        doc_record["question_types"]       = analysis.get("question_types", [])
        doc_record["high_frequency_topics"] = analysis.get("high_frequency_topics", [])

    doc_id = docs_collection.insert_one(doc_record).inserted_id

    saved_tasks = []
    for task in analysis.get("tasks", []):
        task_doc = {
            "title":           task.get("title", "Untitled Task"),
            "due_date":        task.get("due_date"),
            "estimated_hours": task.get("estimated_hours", 1),
            "type":            task.get("type", "other"),
            "priority":        task.get("priority", 70),
            "complexity":      task.get("complexity", "medium"),
            "topics":          analysis.get("topics", []),
            "status":          "pending",
            "doc_id":          str(doc_id),
            "doc_type":        doc_type,
            "course_code":     course_code,
            "filename":        filename,
            "created_at":      datetime.utcnow(),
            "updated_at":      datetime.utcnow()
        }

        clean_copy = {
            k: v.isoformat() if isinstance(v, datetime) else v
            for k, v in task_doc.items()
        }

        tasks_collection.insert_one(task_doc)
        saved_tasks.append(clean_copy)

    return str(doc_id), saved_tasks


# ── Main entry point ───────────────────────────────────────────
def process_pdf(pdf_path: str, filename: str,
                doc_type: str = "assignment",
                course_code: str = None) -> dict:

    print(f"[processor] Starting: {filename} (type={doc_type}, course={course_code})")

    text = extract_text_from_pdf(pdf_path)
    print(f"[processor] Extracted {len(text)} chars from {filename}")

    analysis = analyze_document(text, filename, doc_type, course_code)
    print(f"[processor] Found {len(analysis.get('tasks', []))} tasks, "
          f"{len(analysis.get('topics', []))} topics")

    doc_id, saved_tasks = save_to_mongodb(filename, analysis, doc_type, course_code)
    print(f"[processor] Saved — doc_id: {doc_id}")

    return {
        "success":    True,
        "doc_id":     doc_id,
        "filename":   filename,
        "doc_type":   doc_type,
        "summary":    analysis.get("summary", ""),
        "topics":     analysis.get("topics", []),
        "tasks_found": len(saved_tasks),
        "tasks":      saved_tasks
    }

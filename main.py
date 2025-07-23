"""
Recruitment Marketplace Prototype using FastAPI

This application implements a minimal recruitment marketplace with two user
roles: candidates and recruiters. Candidates can upload documents and browse
job postings, while recruiters can create job postings and view candidates.
Both roles can exchange direct messages. A simple session mechanism using
randomly generated session IDs is implemented to keep users logged in.

The application relies only on Python's standard library and the pre‑installed
packages FastAPI, starlette, and jinja2. Data is persisted in a SQLite
database located in the project directory (``database.db``). Uploaded
documents are stored in the ``uploads/`` folder. This solution is entirely
open source and does not depend on any proprietary services.
"""

import os
import sqlite3
import hashlib
import secrets
import datetime
from typing import Optional, Dict, Tuple, List

from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


# ---------------------------------------------------------------------------
# Database helpers
#
DATABASE_PATH = os.path.join(os.path.dirname(__file__), "database.db")
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")

# Ensure upload directory exists
os.makedirs(UPLOAD_DIR, exist_ok=True)


def get_db_connection() -> sqlite3.Connection:
    """Return a SQLite3 connection with row_factory returning dict-like rows."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize database tables if they don't exist."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('candidate','recruiter'))
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            original_name TEXT NOT NULL,
            uploaded_at DATETIME NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS job_postings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recruiter_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            location TEXT,
            salary_range TEXT,
            created_at DATETIME NOT NULL,
            FOREIGN KEY(recruiter_id) REFERENCES users(id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME NOT NULL,
            FOREIGN KEY(sender_id) REFERENCES users(id),
            FOREIGN KEY(receiver_id) REFERENCES users(id)
        )
        """
    )
    conn.commit()
    conn.close()


# Initialize database when module is imported
init_db()


# ---------------------------------------------------------------------------
# Session management
#
# For this prototype, sessions are kept in memory. Each logged in user will
# have an entry in the sessions dictionary mapping a session ID to a user ID.
# When the server restarts, all sessions are lost. In a production
# implementation you would store sessions in a more durable storage or use a
# token based authentication mechanism.

sessions: Dict[str, int] = {}


def create_session(user_id: int) -> str:
    """Create a new session for the given user and return its session ID."""
    session_id = secrets.token_hex(16)
    sessions[session_id] = user_id
    return session_id


def get_current_user(request: Request) -> Optional[sqlite3.Row]:
    """Return the user row corresponding to the session cookie, if present."""
    session_id = request.cookies.get("session_id")
    if session_id and session_id in sessions:
        user_id = sessions.get(session_id)
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()
        return user
    return None


def hash_password(password: str) -> str:
    """Return SHA256 hash of the given password."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# FastAPI application and routes

app = FastAPI(title="Recruitment Marketplace Prototype")

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

# Mount the uploads directory to serve uploaded documents
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


def login_required(role: Optional[str] = None):
    """
    Decorator generator to enforce that a user is logged in and optionally has
    a specific role. Returns a function that can be used as dependency in
    route definitions.
    """

    async def dependency(request: Request) -> sqlite3.Row:
        user = get_current_user(request)
        if user is None:
            # Not logged in: redirect to login page
            raise RedirectResponse(url="/login")
        if role and user["role"] != role:
            # Wrong role: redirect to appropriate dashboard
            if user["role"] == "candidate":
                raise RedirectResponse(url="/candidate/dashboard")
            else:
                raise RedirectResponse(url="/recruiter/dashboard")
        return user

    return dependency


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page: show welcome message and navigation based on login status."""
    user = get_current_user(request)
    return templates.TemplateResponse("home.html", {"request": request, "user": user})


@app.get("/register", response_class=HTMLResponse)
async def register_form(request: Request, role: str = "candidate"):
    """Display the registration form. Role parameter chooses candidate or recruiter."""
    role = role.lower()
    if role not in ("candidate", "recruiter"):
        role = "candidate"
    return templates.TemplateResponse(
        "register.html", {"request": request, "role": role, "error": None}
    )


@app.post("/register", response_class=HTMLResponse)
async def register(request: Request, username: str = Form(...), password: str = Form(...), role: str = Form(...)):
    """Handle registration POST: create user in database if username is free."""
    role = role.lower()
    if role not in ("candidate", "recruiter"):
        role = "candidate"
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, hash_password(password), role),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        # Username already exists
        conn.close()
        return templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "role": role,
                "error": f"Username '{username}' is already taken. Please choose another.",
            },
        )
    conn.close()
    # Automatically log the user in after registration
    user = None
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    session_id = create_session(user["id"])
    response = RedirectResponse(url=f"/{role}/dashboard", status_code=302)
    response.set_cookie(key="session_id", value=session_id, httponly=True, max_age=3600 * 24)
    return response


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, role: Optional[str] = None):
    """Display login form. Optionally pre-select a role for user guidance."""
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login", response_class=HTMLResponse)
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    """Handle login: validate credentials and create session."""
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if user is None or user["password_hash"] != hash_password(password):
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Invalid username or password. Please try again.",
            },
        )
    session_id = create_session(user["id"])
    # Redirect to role dashboard
    role = user["role"]
    response = RedirectResponse(url=f"/{role}/dashboard", status_code=302)
    response.set_cookie(key="session_id", value=session_id, httponly=True, max_age=3600 * 24)
    return response


@app.get("/logout")
async def logout(request: Request):
    """Log user out by deleting session and clearing cookie."""
    session_id = request.cookies.get("session_id")
    if session_id and session_id in sessions:
        sessions.pop(session_id)
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie(key="session_id")
    return response


# ---------------------------------------------------------------------------
# Candidate routes

@app.get("/candidate/dashboard", response_class=HTMLResponse)
async def candidate_dashboard(request: Request, user: sqlite3.Row = Depends(login_required("candidate"))):
    """Candidate dashboard: list uploaded documents and job postings."""
    # Fetch candidate documents
    conn = get_db_connection()
    docs = conn.execute(
        "SELECT id, filename, original_name, uploaded_at FROM documents WHERE user_id = ? ORDER BY uploaded_at DESC",
        (user["id"],),
    ).fetchall()
    # Fetch all job postings
    jobs = conn.execute(
        "SELECT jp.id, jp.title, jp.description, jp.location, jp.salary_range, jp.created_at, u.username AS recruiter_username "
        "FROM job_postings jp JOIN users u ON jp.recruiter_id = u.id ORDER BY jp.created_at DESC"
    ).fetchall()
    conn.close()
    return templates.TemplateResponse(
        "candidate_dashboard.html",
        {
            "request": request,
            "user": user,
            "documents": docs,
            "job_postings": jobs,
        },
    )


@app.post("/candidate/upload", response_class=RedirectResponse)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    user: sqlite3.Row = Depends(login_required("candidate")),
):
    """Handle document upload for candidates."""
    if not file.filename:
        return RedirectResponse(url="/candidate/dashboard", status_code=302)
    # Save file to uploads directory under user ID
    user_dir = os.path.join(UPLOAD_DIR, str(user["id"]))
    os.makedirs(user_dir, exist_ok=True)
    # Ensure unique filename by prefixing timestamp and random suffix
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    random_suffix = secrets.token_hex(4)
    ext = os.path.splitext(file.filename)[1]
    unique_name = f"{timestamp}_{random_suffix}{ext}"
    file_path = os.path.join(user_dir, unique_name)
    with open(file_path, "wb") as f:
        f.write(await file.read())
    # Insert metadata into database
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO documents (user_id, filename, original_name, uploaded_at) VALUES (?, ?, ?, ?)",
        (
            user["id"],
            f"{user['id']}/{unique_name}",
            file.filename,
            datetime.datetime.utcnow(),
        ),
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/candidate/dashboard", status_code=302)


@app.get("/candidate/messages", response_class=HTMLResponse)
async def candidate_messages(request: Request, user: sqlite3.Row = Depends(login_required("candidate"))):
    """Display messages for candidates: list conversations and current chat."""
    # Determine conversation partner from query parameter
    partner_username = request.query_params.get("with")
    conn = get_db_connection()
    # Get a list of all recruiters (conversation partners) the candidate has communicated with
    partners = conn.execute(
        "SELECT DISTINCT u.id AS id, u.username AS username FROM users u JOIN messages m "
        "ON (u.id = m.sender_id OR u.id = m.receiver_id) WHERE (? IN (m.sender_id, m.receiver_id)) AND u.role = 'recruiter' AND u.id != ?",
        (user["id"], user["id"]),
    ).fetchall()
    current_partner = None
    messages = []
    if partner_username:
        # fetch partner row
        current_partner = conn.execute(
            "SELECT * FROM users WHERE username = ? AND role = 'recruiter'", (partner_username,)
        ).fetchone()
        if current_partner:
            # fetch messages between candidate and partner ordered by timestamp
            messages = conn.execute(
                "SELECT m.*, s.username AS sender_username, r.username AS receiver_username FROM messages m "
                "JOIN users s ON m.sender_id = s.id JOIN users r ON m.receiver_id = r.id "
                "WHERE (m.sender_id = ? AND m.receiver_id = ?) OR (m.sender_id = ? AND m.receiver_id = ?) "
                "ORDER BY m.timestamp ASC",
                (
                    user["id"],
                    current_partner["id"],
                    current_partner["id"],
                    user["id"],
                ),
            ).fetchall()
    conn.close()
    return templates.TemplateResponse(
        "messages.html",
        {
            "request": request,
            "user": user,
            "partners": partners,
            "current_partner": current_partner,
            "messages": messages,
        },
    )


@app.post("/candidate/message/send")
async def candidate_send_message(
    request: Request,
    to_username: str = Form(...),
    content: str = Form(...),
    user: sqlite3.Row = Depends(login_required("candidate")),
):
    """Send a message from candidate to a recruiter."""
    # Validate partner exists and is recruiter
    conn = get_db_connection()
    partner = conn.execute(
        "SELECT * FROM users WHERE username = ? AND role = 'recruiter'", (to_username,)
    ).fetchone()
    if partner and content.strip():
        conn.execute(
            "INSERT INTO messages (sender_id, receiver_id, content, timestamp) VALUES (?, ?, ?, ?)",
            (
                user["id"],
                partner["id"],
                content.strip(),
                datetime.datetime.utcnow(),
            ),
        )
        conn.commit()
    conn.close()
    return RedirectResponse(url=f"/candidate/messages?with={to_username}", status_code=302)


# ---------------------------------------------------------------------------
# Recruiter routes

@app.get("/recruiter/dashboard", response_class=HTMLResponse)
async def recruiter_dashboard(request: Request, user: sqlite3.Row = Depends(login_required("recruiter"))):
    """Recruiter dashboard: list job postings and provide creation form."""
    conn = get_db_connection()
    jobs = conn.execute(
        "SELECT * FROM job_postings WHERE recruiter_id = ? ORDER BY created_at DESC",
        (user["id"],),
    ).fetchall()
    # Fetch candidate list for quick access
    candidates = conn.execute(
        "SELECT id, username FROM users WHERE role = 'candidate' ORDER BY username ASC"
    ).fetchall()
    conn.close()
    return templates.TemplateResponse(
        "recruiter_dashboard.html",
        {
            "request": request,
            "user": user,
            "job_postings": jobs,
            "candidates": candidates,
        },
    )


@app.post("/recruiter/job/create")
async def create_job(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    location: str = Form(None),
    salary_range: str = Form(None),
    user: sqlite3.Row = Depends(login_required("recruiter")),
):
    """Create a new job posting by recruiter."""
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO job_postings (recruiter_id, title, description, location, salary_range, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            user["id"],
            title,
            description,
            location or "",
            salary_range or "",
            datetime.datetime.utcnow(),
        ),
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/recruiter/dashboard", status_code=302)


@app.get("/recruiter/candidates", response_class=HTMLResponse)
async def recruiter_candidates(request: Request, user: sqlite3.Row = Depends(login_required("recruiter"))):
    """View list of candidates and their documents."""
    conn = get_db_connection()
    candidates = conn.execute(
        "SELECT id, username FROM users WHERE role = 'candidate' ORDER BY username ASC"
    ).fetchall()
    # Optionally pick a candidate to view documents
    candidate_username = request.query_params.get("username")
    selected_candidate = None
    docs: List[sqlite3.Row] = []
    if candidate_username:
        selected_candidate = conn.execute(
            "SELECT * FROM users WHERE username = ? AND role = 'candidate'",
            (candidate_username,),
        ).fetchone()
        if selected_candidate:
            docs = conn.execute(
                "SELECT id, filename, original_name, uploaded_at FROM documents WHERE user_id = ? ORDER BY uploaded_at DESC",
                (selected_candidate["id"],),
            ).fetchall()
    conn.close()
    return templates.TemplateResponse(
        "recruiter_candidates.html",
        {
            "request": request,
            "user": user,
            "candidates": candidates,
            "selected_candidate": selected_candidate,
            "documents": docs,
        },
    )


@app.get("/recruiter/messages", response_class=HTMLResponse)
async def recruiter_messages(request: Request, user: sqlite3.Row = Depends(login_required("recruiter"))):
    """Display messages for recruiters."""
    partner_username = request.query_params.get("with")
    conn = get_db_connection()
    # Get list of candidates the recruiter has communicated with
    partners = conn.execute(
        "SELECT DISTINCT u.id AS id, u.username AS username FROM users u JOIN messages m "
        "ON (u.id = m.sender_id OR u.id = m.receiver_id) WHERE (? IN (m.sender_id, m.receiver_id)) "
        "AND u.role = 'candidate' AND u.id != ?",
        (user["id"], user["id"]),
    ).fetchall()
    current_partner = None
    messages = []
    if partner_username:
        current_partner = conn.execute(
            "SELECT * FROM users WHERE username = ? AND role = 'candidate'", (partner_username,)
        ).fetchone()
        if current_partner:
            messages = conn.execute(
                "SELECT m.*, s.username AS sender_username, r.username AS receiver_username FROM messages m "
                "JOIN users s ON m.sender_id = s.id JOIN users r ON m.receiver_id = r.id "
                "WHERE (m.sender_id = ? AND m.receiver_id = ?) OR (m.sender_id = ? AND m.receiver_id = ?) "
                "ORDER BY m.timestamp ASC",
                (
                    user["id"],
                    current_partner["id"],
                    current_partner["id"],
                    user["id"],
                ),
            ).fetchall()
    conn.close()
    return templates.TemplateResponse(
        "messages.html",
        {
            "request": request,
            "user": user,
            "partners": partners,
            "current_partner": current_partner,
            "messages": messages,
        },
    )


@app.post("/recruiter/message/send")
async def recruiter_send_message(
    request: Request,
    to_username: str = Form(...),
    content: str = Form(...),
    user: sqlite3.Row = Depends(login_required("recruiter")),
):
    """Send a message from recruiter to a candidate."""
    conn = get_db_connection()
    partner = conn.execute(
        "SELECT * FROM users WHERE username = ? AND role = 'candidate'", (to_username,)
    ).fetchone()
    if partner and content.strip():
        conn.execute(
            "INSERT INTO messages (sender_id, receiver_id, content, timestamp) VALUES (?, ?, ?, ?)",
            (
                user["id"],
                partner["id"],
                content.strip(),
                datetime.datetime.utcnow(),
            ),
        )
        conn.commit()
    conn.close()
    return RedirectResponse(url=f"/recruiter/messages?with={to_username}", status_code=302)


# ---------------------------------------------------------------------------
# Template utilities

# Register a Jinja2 filter to format datetimes in a readable way
def datetime_format(value: datetime.datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime.datetime) else str(value)


templates.env.filters["datetime_format"] = datetime_format

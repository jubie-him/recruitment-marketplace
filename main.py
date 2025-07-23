"""
Recruitment Marketplace Platform
--------------------------------

This is a basic prototype of a recruitment marketplace built using FastAPI and
the Deta platform.  The application provides two primary user roles: **job
seekers** and **recruiters**.

Job seekers can register, log in, browse available jobs and apply to them by
submitting their details and uploading a resume.  Recruiters can create job
postings, review applicants and download uploaded resumes.  Data is persisted
using Deta Base (a simple NoSQL database) and resumes are stored in Deta
Drive.  Sessions are handled via cookies with a server‑generated session
token.  This code is intentionally simple to focus on demonstrating core
functionality rather than production‑ready features such as robust security,
validation and error handling.

To run locally install the dependencies from ``requirements.txt`` and start
the app with ``uvicorn main:app --reload``.  When deploying to Deta you do
not need a separate server; the Deta runtime automatically serves your FastAPI
application.
"""

from __future__ import annotations

import os
import uuid
import hashlib
from typing import Optional, Dict, Any

from fastapi import (
    FastAPI,
    Request,
    Form,
    UploadFile,
    File,
    Depends,
    HTTPException,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

# When running on Deta the `deta` module will be available.  When running
# locally without Deta (for example during development), fallback to a simple
# in‑memory store so that the app can be exercised without an account.  This
# fallback is deliberately simplistic and should not be used for anything
# beyond testing.
try:
    from deta import Deta  # type: ignore
    _DETA_AVAILABLE = True
except ImportError:
    Deta = None  # type: ignore
    _DETA_AVAILABLE = False


class InMemoryBase:
    """Minimal in‑memory replacement for Deta Base used for local testing."""

    def __init__(self, name: str):
        self._items: Dict[str, Dict[str, Any]] = {}

    def put(self, data: Dict[str, Any]) -> Dict[str, Any]:
        key = data.get("key") or str(uuid.uuid4())
        data["key"] = key
        self._items[key] = data
        return data

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        return self._items.get(key)

    def fetch(self, query: Optional[Dict[str, Any]] = None) -> Any:
        # Emulate Deta Base fetch.  This returns an object with an ``items``
        # attribute containing a list of matching entries.  We ignore paging.
        class _Result:
            def __init__(self, items):
                self.items = items

        if not query:
            return _Result(list(self._items.values()))
        # All query keys must match exactly.
        items = [v for v in self._items.values() if all(v.get(k) == val for k, val in query.items())]
        return _Result(items)

    def delete(self, key: str) -> None:
        self._items.pop(key, None)


class InMemoryDrive:
    """Minimal in‑memory replacement for Deta Drive used for local testing."""

    def __init__(self, name: str):
        self._files: Dict[str, bytes] = {}

    def put(self, name: str, data: bytes | UploadFile) -> None:
        if isinstance(data, UploadFile):
            content = data.file.read()
        else:
            content = data
        self._files[name] = content

    def get(self, name: str) -> Any:
        # Return a file‑like object that can be read.  In Deta Drive the
        # returned object has a ``read`` method.  We'll emulate that.
        content = self._files.get(name)
        if content is None:
            return None
        return type("_File", (), {"read": lambda self_: content})()

    def delete(self, name: str) -> None:
        self._files.pop(name, None)


def get_deta_instances() -> tuple[Any, Any, Any, Any]:
    """
    Acquire instances of Deta Base and Drive for users, jobs, applications and
    resumes.  When running on Deta the ``DETA_PROJECT_KEY`` environment
    variable will be available and the real Deta classes will be used.  When
    running locally fallback to in‑memory stores.
    """
    if _DETA_AVAILABLE and os.getenv("DETA_PROJECT_KEY"):
        deta = Deta(os.getenv("DETA_PROJECT_KEY"))
        users_db = deta.Base("users")
        jobs_db = deta.Base("jobs")
        applications_db = deta.Base("applications")
        sessions_db = deta.Base("sessions")
        resumes_drive = deta.Drive("resumes")
        return users_db, jobs_db, applications_db, sessions_db, resumes_drive
    # Local fallback
    users_db = InMemoryBase("users")
    jobs_db = InMemoryBase("jobs")
    applications_db = InMemoryBase("applications")
    sessions_db = InMemoryBase("sessions")
    resumes_drive = InMemoryDrive("resumes")
    return users_db, jobs_db, applications_db, sessions_db, resumes_drive


# Initialise data stores
users_db, jobs_db, applications_db, sessions_db, resumes_drive = get_deta_instances()


app = FastAPI()

# Jinja2 templates live in the ``templates`` directory.
templates = Jinja2Templates(directory=str(os.path.join(os.path.dirname(__file__), "templates")))
# Provide a global ``year`` variable for the templates (used in the footer).
from datetime import datetime
templates.env.globals['year'] = datetime.utcnow().year

# Serve static files (CSS) from the ``static`` directory
app.mount(
    "/static",
    StaticFiles(directory=str(os.path.join(os.path.dirname(__file__), "static"))),
    name="static",
)


def hash_password(password: str) -> str:
    """Hash a password using SHA256."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return hash_password(password) == password_hash


def create_session(user_key: str) -> str:
    """Create a new session token for a given user key and persist it."""
    token = str(uuid.uuid4())
    sessions_db.put({"key": token, "user_key": user_key})
    return token


def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    """Return the current logged in user based on the session cookie."""
    token = request.cookies.get("session_token")
    if not token:
        return None
    session = sessions_db.get(token)
    if not session:
        return None
    user_key = session.get("user_key")
    if not user_key:
        return None
    user = users_db.get(user_key)
    return user


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, user: Optional[Dict[str, Any]] = Depends(get_current_user)):
    """Render the landing page.  Shows available jobs and login/register options."""
    # Fetch all jobs to display on the home page
    jobs_result = jobs_db.fetch()
    jobs = jobs_result.items if jobs_result else []
    return templates.TemplateResponse(
        "home.html",
        {"request": request, "user": user, "jobs": jobs},
    )


@app.get("/register", response_class=HTMLResponse)
async def register_get(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@app.post("/register")
async def register_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    user_type: str = Form(...),
):
    # Check if username already exists
    existing = users_db.fetch({"username": username})
    if existing and existing.items:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Username already exists."},
        )
    # Create new user
    user_key = f"u-{uuid.uuid4().hex}"
    users_db.put(
        {
            "key": user_key,
            "username": username,
            "password_hash": hash_password(password),
            "user_type": user_type,
        }
    )
    # Automatically log in the user
    token = create_session(user_key)
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    response.set_cookie("session_token", token, httponly=True)
    return response


@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    # Find user by username
    result = users_db.fetch({"username": username})
    user = result.items[0] if result and result.items else None
    if not user or not verify_password(password, user.get("password_hash", "")):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid username or password."},
        )
    # Create session and redirect to dashboard
    token = create_session(user["key"])
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    response.set_cookie("session_token", token, httponly=True)
    return response


@app.get("/logout")
async def logout(request: Request):
    # Remove session from database and clear cookie
    token = request.cookies.get("session_token")
    if token:
        sessions_db.delete(token)
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("session_token")
    return response


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user: Optional[Dict[str, Any]] = Depends(get_current_user)):
    if not user:
        return RedirectResponse("/login", status_code=status.HTTP_302_FOUND)
    # Determine what to show based on user_type
    if user["user_type"] == "jobseeker":
        jobs = jobs_db.fetch().items
        # Also fetch applications for this user
        applications = applications_db.fetch({"user_key": user["key"]}).items
        applied_job_ids = {app["job_key"] for app in applications}
        return templates.TemplateResponse(
            "dashboard_jobseeker.html",
            {
                "request": request,
                "user": user,
                "jobs": jobs,
                "applied_job_ids": applied_job_ids,
            },
        )
    else:  # recruiter
        # Fetch jobs created by this recruiter
        jobs = jobs_db.fetch({"recruiter_key": user["key"]}).items
        return templates.TemplateResponse(
            "dashboard_recruiter.html",
            {"request": request, "user": user, "jobs": jobs},
        )


@app.get("/jobs/{job_key}", response_class=HTMLResponse)
async def job_detail(
    job_key: str, request: Request, user: Optional[Dict[str, Any]] = Depends(get_current_user)
):
    job = jobs_db.get(job_key)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    # Check if user already applied
    applied = False
    if user and user["user_type"] == "jobseeker":
        apps = applications_db.fetch({"job_key": job_key, "user_key": user["key"]}).items
        applied = len(apps) > 0
    return templates.TemplateResponse(
        "job_detail.html",
        {"request": request, "user": user, "job": job, "applied": applied},
    )


@app.post("/jobs/{job_key}/apply")
async def apply_job(
    job_key: str,
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    resume: UploadFile = File(...),
    user: Optional[Dict[str, Any]] = Depends(get_current_user),
):
    # Only jobseekers can apply
    if not user or user["user_type"] != "jobseeker":
        raise HTTPException(status_code=403, detail="Not authorized")
    # Prevent duplicate applications
    existing = applications_db.fetch({"job_key": job_key, "user_key": user["key"]}).items
    if existing:
        return RedirectResponse(f"/jobs/{job_key}", status_code=status.HTTP_302_FOUND)
    # Save resume
    resume_filename = f"{uuid.uuid4().hex}_{resume.filename}"
    # Deta Drive expects raw bytes or file‑like object; we use UploadFile.file
    resumes_drive.put(resume_filename, resume)
    # Save application
    applications_db.put(
        {
            "key": f"a-{uuid.uuid4().hex}",
            "job_key": job_key,
            "user_key": user["key"],
            "full_name": full_name,
            "email": email,
            "resume_filename": resume_filename,
        }
    )
    return RedirectResponse(f"/dashboard", status_code=status.HTTP_302_FOUND)


@app.get("/recruiter/jobs/create", response_class=HTMLResponse)
async def create_job_get(request: Request, user: Optional[Dict[str, Any]] = Depends(get_current_user)):
    # Only recruiters can create jobs
    if not user or user["user_type"] != "recruiter":
        raise HTTPException(status_code=403, detail="Not authorized")
    return templates.TemplateResponse("create_job.html", {"request": request, "user": user})


@app.post("/recruiter/jobs/create")
async def create_job_post(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    location: str = Form(...),
    user: Optional[Dict[str, Any]] = Depends(get_current_user),
):
    if not user or user["user_type"] != "recruiter":
        raise HTTPException(status_code=403, detail="Not authorized")
    job_key = f"j-{uuid.uuid4().hex}"
    jobs_db.put(
        {
            "key": job_key,
            "title": title,
            "description": description,
            "location": location,
            "recruiter_key": user["key"],
        }
    )
    return RedirectResponse("/dashboard", status_code=status.HTTP_302_FOUND)


@app.get("/recruiter/jobs/{job_key}/applicants", response_class=HTMLResponse)
async def view_applicants(
    job_key: str,
    request: Request,
    user: Optional[Dict[str, Any]] = Depends(get_current_user),
):
    if not user or user["user_type"] != "recruiter":
        raise HTTPException(status_code=403, detail="Not authorized")
    job = jobs_db.get(job_key)
    if not job or job.get("recruiter_key") != user["key"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    # Fetch applicants
    applicants = applications_db.fetch({"job_key": job_key}).items
    return templates.TemplateResponse(
        "applicants.html",
        {"request": request, "user": user, "job": job, "applicants": applicants},
    )


@app.get("/resume/{filename}")
async def download_resume(filename: str):
    # Provide a simple way to download resumes
    file_obj = resumes_drive.get(filename)
    if not file_obj:
        raise HTTPException(status_code=404, detail="Resume not found")
    content = file_obj.read()
    return Response(content, media_type="application/octet-stream", headers={"Content-Disposition": f"attachment; filename={filename}"})

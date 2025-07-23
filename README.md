# Recruitment Marketplace Prototype

This repository contains a fully open‑source recruitment marketplace built with
[FastAPI](https://fastapi.tiangolo.com/). The platform provides two types of
users—candidates and recruiters—with distinct capabilities:

## Features

### Candidates

* Register and log in as a candidate.
* Upload and store personal documents/credentials (e.g., resumes, certificates).
* Browse available job postings created by recruiters.
* Send and receive direct messages with recruiters.

### Recruiters

* Register and log in as a recruiter.
* Create job postings describing open positions.
* Browse registered candidates and view their uploaded documents.
* Initiate and respond to direct messages with candidates.

## Technology

The application is implemented entirely using open‑source technology and Python's
standard library:

* **FastAPI** – lightweight web framework for routing and dependency injection.
* **SQLite** – simple file‑based relational database; no external database
  server required.
* **Jinja2** – templating engine for server‑side HTML rendering.
* **Uvicorn** – ASGI server to run the FastAPI application.

## Installation & Running

To run the application locally, you will need Python 3.11+ with `pip`
available. Follow these steps from the root of the repository:

```bash
# Create and activate a virtual environment (optional but recommended)
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the development server
uvicorn recruitment_app.main:app --reload --host 0.0.0.0 --port 8000

```

Once the server is running, open your browser to `http://localhost:8000`.

### Note on `python-multipart`

`python-multipart` is required by FastAPI to parse form and file upload data.
It is an open‑source library and is installed automatically via the
requirements file. If you omit it, form submissions will fail with an
informative error.

## Directory Structure

```
recruitment_app/
├── main.py            # FastAPI application with routing and business logic
├── templates/         # Jinja2 HTML templates
│   ├── base.html
│   ├── home.html
│   ├── register.html
│   ├── login.html
│   ├── candidate_dashboard.html
│   ├── recruiter_dashboard.html
│   ├── recruiter_candidates.html
│   └── messages.html
├── uploads/           # Uploaded documents (created at runtime)
├── database.db        # SQLite database (created at runtime)
├── requirements.txt   # Python dependencies
└── README.md          # This file
```

## Limitations & Future Work

* **Session Storage** – Sessions are stored in memory. A restart will log
  everyone out. Consider using a persistent session store (e.g., Redis) or
  token‑based authentication.
* **No Real‑Time Messaging** – Messages are stored and displayed on page
  refresh. For a real product, integrate WebSockets (e.g., via FastAPI
  `websockets` or [Starlette's WebSocket support](https://www.starlette.io/websocket/)).
* **Bulk Candidate Outreach** – A stub for uploading bulk contacts to invite
  candidates is mentioned but not implemented. This would require CSV
  processing and email/SMS integration.
* **Security** – Passwords are hashed with SHA‑256 for simplicity. For
  production use, choose a strong hashing algorithm (e.g., bcrypt/Argon2) and
  protect against CSRF attacks.
* **Asynchronous File Storage** – File uploads are saved synchronously to the
  filesystem. Consider streaming large files and validating file types and
  sizes.

Despite these limitations, the provided prototype demonstrates the core
workflows of a recruitment platform using only open‑source components and
standard Python libraries.
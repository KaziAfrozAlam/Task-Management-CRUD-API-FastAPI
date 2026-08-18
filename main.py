import os
import logging
logging.basicConfig(level=logging.INFO)
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from llm.schema import TriageOutput, Category, Urgency, Team
from typing import Optional
from pydantic import BaseModel
from supabase_client import supabase
from llm.client import call_triage_model, ModelOutputError, ModelDisabledError
from openai import APITimeoutError, APIStatusError
from llm.quarantine import log_quarantine
load_dotenv()

app = FastAPI()
security = HTTPBearer()

DATABASE_URL = os.environ["DATABASE_URL"]


def get_connection():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    done BOOLEAN NOT NULL DEFAULT FALSE
                )
            """)

            cursor.execute("SELECT COUNT(*) FROM tasks")
            count = cursor.fetchone()["count"]

            if count == 0:
                seed_tasks = [
                    ("Learn FastAPI", False),
                    ("Build CRUD API", False),
                    ("Publish to GitHub", False),
                ]
                cursor.executemany(
                    "INSERT INTO tasks (title, done) VALUES (%s, %s)", seed_tasks
                )

        conn.commit()
    finally:
        conn.close()


init_db()

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    token = credentials.credentials

    try:
        response = supabase.auth.get_user(token)

        if response.user is None:
            raise HTTPException(
                status_code=401,
                detail={"error": "Invalid or expired token"},
            )

        return response.user

    except Exception:
        raise HTTPException(
            status_code=401,
            detail={"error": "Invalid or expired token"},
        )

class CreateTask(BaseModel):
    title: str

class AuthRequest(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None

class TriageRequest(BaseModel):
    text: str | None = None    

@app.get("/", summary="Root endpoint")
def root():
    return {
        "name": "Task API",
        "version": "1.0",
        "endpoints": [
            "/tasks",
            "/auth/signup",
            "/auth/login",
            "/public/info",
            "/protected/profile",
            "/admin",
        ],
    }
@app.get("/health", summary="Health check")
def health():
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
        finally:
            conn.close()
        return {"status": "ok", "db": "ok"}
    except Exception:
        raise HTTPException(status_code=503, detail={"status": "error", "db": "unreachable"})

@app.post("/auth/signup", status_code=201, summary="Create a new user account") 
def signup(auth: AuthRequest):
    # Validate input
    if not auth.email or not auth.password:
        raise HTTPException(
            status_code=400,
            detail={"error": "Email and password are required"}, 
        )

    if not auth.email.strip() or not auth.password.strip():
        raise HTTPException(
            status_code=400,
            detail={"error": "Email and password cannot be empty"},
        )

    try:
        response = supabase.auth.sign_up(
            {
                "email": auth.email,
                "password": auth.password,
            }
        )

        if response.user is None:
            raise HTTPException(
                status_code=400,
                detail={"error": "Signup failed"},
            )

        return response.user

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail={"error": str(e)},
        )

@app.post("/auth/login", summary="Login and receive JWT tokens")
def login(auth: AuthRequest):
    # Validate input
    if not auth.email or not auth.password:
        raise HTTPException(
            status_code=400,
            detail={"error": "Email and password are required"},
        )

    if not auth.email.strip() or not auth.password.strip():
        raise HTTPException(
            status_code=400,
            detail={"error": "Email and password cannot be empty"},
        )

    try:
        response = supabase.auth.sign_in_with_password(
            {
                "email": auth.email,
                "password": auth.password,
            }
        )

        return {
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
        }

    except Exception:
        raise HTTPException(
            status_code=401,
            detail={"error": "Invalid login credentials"},
        )    

@app.get("/public/info", summary="Public information")
def public_info():
    return {
        "message": "Welcome stranger! This info is public."
    }

@app.get(
    "/protected/profile",
    summary="Authenticated user profile"
)
def protected_profile(
    user=Depends(get_current_user),
):
    return {
        "id": user.id,
        "email": user.email,
    } 


@app.get("/admin", summary="Admin only")
def admin_route(user=Depends(get_current_user)):
    if user.email != "admin@example.com":
        raise HTTPException(
            status_code=403,
            detail={"error": "Forbidden: Admin access only"},
        )

    return {
        "message": "Welcome Admin!"
    }

@app.get("/tasks", summary="Get all tasks")
def get_tasks(user=Depends(get_current_user)):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM tasks")
            rows = cursor.fetchall()
        return rows
    finally:
        conn.close()

@app.get("/tasks/{task_id}", summary="Get a single task by ID")
def get_task(
    task_id: int,
    user=Depends(get_current_user),
):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
            row = cursor.fetchone()
    finally:
        conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return row

@app.post("/tasks", status_code=201, summary="Create a new task")
def create_task(
    task: CreateTask,
    user=Depends(get_current_user),
):
    if not task.title or not task.title.strip():
        raise HTTPException(status_code=400, detail="Title is required and cannot be empty")

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO tasks (title, done) VALUES (%s, %s) RETURNING *",
                (task.title, False),
            )
            new_task = cursor.fetchone()
        conn.commit()
    finally:
        conn.close()

    return new_task

class UpdatedTask(BaseModel):
    title: str | None = None
    done: bool | None = None

@app.put("/tasks/{task_id}", summary="Update a task's title or done status")
def update_task(
    task_id: int,
    update: UpdatedTask,
    user=Depends(get_current_user),
):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
            row = cursor.fetchone()

            if row is None:
                raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

            new_title = row["title"]
            new_done = row["done"]

            if update.title is not None:
                if not update.title.strip():
                    raise HTTPException(status_code=400, detail="Title cannot be empty")
                new_title = update.title

            if update.done is not None:
                new_done = update.done

            cursor.execute(
                "UPDATE tasks SET title = %s, done = %s WHERE id = %s",
                (new_title, new_done, task_id),
            )
            conn.commit()

            cursor.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
            updated_row = cursor.fetchone()
        return updated_row
    finally:
        conn.close()

@app.delete("/tasks/{task_id}", status_code=204, summary="Delete a task")
def delete_task(
    task_id: int,
    user=Depends(get_current_user),
):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
            row = cursor.fetchone()

            if row is None:
                raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

            cursor.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
        conn.commit()
    finally:
        conn.close()
    return

@app.post("/triage", response_model=TriageOutput, summary="Classify a support message")
def triage(payload: TriageRequest):
    if not payload.text or not payload.text.strip():
        raise HTTPException(
            status_code=400,
            detail={"error": "text is required and cannot be empty"},
        )

    if len(payload.text) > 2000:
        raise HTTPException(
            status_code=400,
            detail={"error": "text must be 2000 characters or fewer"},
        )

    if os.environ.get("LLM_STUB") == "1":
        return TriageOutput(
            category=Category.other,
            urgency=Urgency.normal,
            suggested_team=Team.support,
            confidence=0.42,
            reason="Stub response — model not called (LLM_STUB=1).",
        )

    try:
        return call_triage_model(payload.text)
    except ModelDisabledError:
        return TriageOutput(
            category=Category.other,
            urgency=Urgency.low,
            suggested_team=Team.support,
            confidence=0.0,
            reason="LLM disabled via kill switch (LLM_ENABLED=false).",
        )
    except APITimeoutError:
        raise HTTPException(
            status_code=504,
            detail={"error": "Model call timed out."},
        )
    except APIStatusError as e:
        raise HTTPException(
            status_code=502,
            detail={"error": f"Model provider returned an error: {e.status_code}"},
        )
    except ModelOutputError as e:
        log_quarantine(
            input_text=payload.text,
            error=e.error,
            raw_output=e.raw_output,
            prompt_version=e.prompt_version,
        )
        raise HTTPException(
            status_code=422,
            detail={"error": "Model output could not be validated after one repair attempt."},
        )
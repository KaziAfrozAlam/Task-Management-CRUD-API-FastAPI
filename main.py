import os
from typing import Annotated

import psycopg
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field

from supabase_client import supabase

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL must be set in the environment or .env file")

app = FastAPI(
    title="Secure Task Management API",
    version="1.0.0",
    description="Task Management REST API secured with Supabase Authentication.",
)
security = HTTPBearer(auto_error=False)


class AuthRequest(BaseModel):
    email: str = Field(min_length=1)
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserProfile(BaseModel):
    id: str
    email: str | None = None


class TaskCreate(BaseModel):
    title: str = Field(min_length=1)
    done: bool = False


class TaskUpdate(BaseModel):
    title: str | None = None
    done: bool | None = None


class Task(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: str
    title: str
    done: bool


def get_connection():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id SERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    done BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """)
            cursor.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS user_id TEXT")
            cursor.execute(
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
            )
            cursor.execute(
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks (user_id)"
            )


init_db()


def bad_request(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST, detail={"error": message}
    )


def unauthorized(message: str = "Invalid or expired token") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail={"error": message}
    )


def validate_task_title(title: str | None, *, field_name: str = "Title") -> str:
    if title is None or not title.strip():
        raise bad_request(f"{field_name} is required and cannot be empty")
    return title.strip()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
):
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized("Missing bearer token")

    try:
        response = supabase.auth.get_user(credentials.credentials)
    except Exception as exc:
        raise unauthorized() from exc

    if response.user is None:
        raise unauthorized()

    return response.user


@app.get("/", summary="Root endpoint")
def root():
    return {
        "name": "Task API",
        "version": "1.0",
        "endpoints": [
            "/auth/signup",
            "/auth/login",
            "/public/info",
            "/protected/profile",
            "/tasks",
        ],
    }


@app.get("/health", summary="Health check")
def health():
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
        return {"status": "ok", "db": "ok"}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "error", "db": "unreachable"},
        ) from exc


@app.post(
    "/auth/signup",
    status_code=status.HTTP_201_CREATED,
    response_model=UserProfile,
    summary="Create a new user account",
)
def signup(auth: AuthRequest):
    password = validate_task_title(auth.password, field_name="Password")

    try:
        response = supabase.auth.sign_up({"email": auth.email, "password": password})
    except Exception as exc:
        raise bad_request(str(exc)) from exc

    if response.user is None:
        raise bad_request("Signup failed")

    return {"id": response.user.id, "email": response.user.email}


@app.post(
    "/auth/login", response_model=TokenResponse, summary="Login and receive JWT tokens"
)
def login(auth: AuthRequest):
    password = validate_task_title(auth.password, field_name="Password")

    try:
        response = supabase.auth.sign_in_with_password(
            {"email": auth.email, "password": password}
        )
    except Exception as exc:
        raise unauthorized("Invalid login credentials") from exc

    if response.session is None:
        raise unauthorized("Invalid login credentials")

    return {
        "access_token": response.session.access_token,
        "refresh_token": response.session.refresh_token,
        "token_type": "bearer",
    }


@app.get("/public/info", summary="Public information")
def public_info():
    return {"message": "This public endpoint does not require authentication."}


@app.get(
    "/protected/profile",
    response_model=UserProfile,
    summary="Authenticated user profile",
)
def protected_profile(user=Depends(get_current_user)):
    return {"id": user.id, "email": user.email}


@app.get("/tasks", response_model=list[Task], summary="Get all tasks")
def get_tasks(user=Depends(get_current_user)):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, user_id, title, done FROM tasks WHERE user_id = %s ORDER BY id",
                (user.id,),
            )
            return cursor.fetchall()


@app.get("/tasks/{task_id}", response_model=Task, summary="Get a single task by ID")
def get_task(task_id: int, user=Depends(get_current_user)):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, user_id, title, done FROM tasks WHERE id = %s AND user_id = %s",
                (task_id, user.id),
            )
            row = cursor.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
        )
    return row


@app.post(
    "/tasks",
    status_code=status.HTTP_201_CREATED,
    response_model=Task,
    summary="Create a new task",
)
def create_task(task: TaskCreate, user=Depends(get_current_user)):
    title = validate_task_title(task.title)

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tasks (user_id, title, done)
                VALUES (%s, %s, %s)
                RETURNING id, user_id, title, done
                """,
                (user.id, title, task.done),
            )
            return cursor.fetchone()


@app.put("/tasks/{task_id}", response_model=Task, summary="Update a task")
def update_task(task_id: int, update: TaskUpdate, user=Depends(get_current_user)):
    if update.title is None and update.done is None:
        raise bad_request("At least one field must be provided")

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, user_id, title, done FROM tasks WHERE id = %s AND user_id = %s",
                (task_id, user.id),
            )
            row = cursor.fetchone()

            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
                )

            title = row["title"]
            if update.title is not None:
                title = validate_task_title(update.title)

            done = row["done"] if update.done is None else update.done

            cursor.execute(
                """
                UPDATE tasks
                SET title = %s, done = %s, updated_at = NOW()
                WHERE id = %s AND user_id = %s
                RETURNING id, user_id, title, done
                """,
                (title, done, task_id, user.id),
            )
            return cursor.fetchone()


@app.delete(
    "/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a task",
)
def delete_task(task_id: int, user=Depends(get_current_user)):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM tasks WHERE id = %s AND user_id = %s RETURNING id",
                (task_id, user.id),
            )
            deleted = cursor.fetchone()

    if deleted is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)

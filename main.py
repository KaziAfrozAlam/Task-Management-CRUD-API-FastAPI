import os
from contextlib import contextmanager
from typing import Annotated

import psycopg
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg.rows import dict_row
from pydantic import BaseModel, EmailStr, Field

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


@contextmanager
def get_connection():
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id SERIAL PRIMARY KEY,
                    user_id UUID NOT NULL,
                    title TEXT NOT NULL,
                    done BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS user_id UUID")
            cursor.execute(
                "ALTER TABLE tasks "
                "ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
            )
            cursor.execute(
                "ALTER TABLE tasks "
                "ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks (user_id)"
            )
        conn.commit()


init_db()


@app.exception_handler(RequestValidationError)
def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": {"error": "Invalid request", "issues": exc.errors()}},
    )


class AuthRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TaskCreate(BaseModel):
    title: str = Field(min_length=1)


class TaskUpdate(BaseModel):
    title: str | None = None
    done: bool | None = None


def normalize_title(title: str) -> str:
    normalized = title.strip()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Title cannot be empty"},
        )
    return normalized


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
):
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Missing bearer token"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        response = supabase.auth.get_user(credentials.credentials)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Invalid or expired token"},
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if response.user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Invalid or expired token"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    return response.user


CurrentUser = Annotated[object, Depends(get_current_user)]


@app.get("/", summary="Root endpoint")
def root():
    return {
        "name": "Secure Task Management API",
        "version": "1.0.0",
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
    summary="Create a new user account",
)
def signup(auth: AuthRequest):
    try:
        response = supabase.auth.sign_up(
            {"email": auth.email, "password": auth.password}
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": str(exc)},
        ) from exc

    if response.user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Signup failed"},
        )

    return {"id": response.user.id, "email": response.user.email}


@app.post(
    "/auth/login", response_model=TokenResponse, summary="Login and receive JWT tokens"
)
def login(auth: AuthRequest):
    try:
        response = supabase.auth.sign_in_with_password(
            {"email": auth.email, "password": auth.password}
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Invalid login credentials"},
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if response.session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Invalid login credentials"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    return TokenResponse(
        access_token=response.session.access_token,
        refresh_token=response.session.refresh_token,
    )


@app.get("/public/info", summary="Public information")
def public_info():
    return {"message": "This endpoint is public and does not require authentication."}


@app.get("/protected/profile", summary="Authenticated user profile")
def protected_profile(user: CurrentUser):
    return {"id": user.id, "email": user.email}


@app.get("/tasks", summary="Get authenticated user's tasks")
def get_tasks(user: CurrentUser):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, title, done, created_at, updated_at "
                "FROM tasks WHERE user_id = %s ORDER BY id",
                (user.id,),
            )
            return cursor.fetchall()


@app.get("/tasks/{task_id}", summary="Get a single task by ID")
def get_task(task_id: int, user: CurrentUser):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, title, done, created_at, updated_at "
                "FROM tasks WHERE id = %s AND user_id = %s",
                (task_id, user.id),
            )
            row = cursor.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": f"Task {task_id} not found"},
        )
    return row


@app.post("/tasks", status_code=status.HTTP_201_CREATED, summary="Create a new task")
def create_task(task: TaskCreate, user: CurrentUser):
    title = normalize_title(task.title)
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tasks (user_id, title, done)
                VALUES (%s, %s, FALSE)
                RETURNING id, title, done, created_at, updated_at
                """,
                (user.id, title),
            )
            new_task = cursor.fetchone()
        conn.commit()
    return new_task


@app.put("/tasks/{task_id}", summary="Update a task's title or done status")
def update_task(task_id: int, update: TaskUpdate, user: CurrentUser):
    if update.title is None and update.done is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "At least one field must be provided"},
        )

    title = normalize_title(update.title) if update.title is not None else None

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM tasks WHERE id = %s AND user_id = %s",
                (task_id, user.id),
            )
            if cursor.fetchone() is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"error": f"Task {task_id} not found"},
                )

            cursor.execute(
                """
                UPDATE tasks
                SET title = COALESCE(%s, title),
                    done = COALESCE(%s, done),
                    updated_at = NOW()
                WHERE id = %s AND user_id = %s
                RETURNING id, title, done, created_at, updated_at
                """,
                (title, update.done, task_id, user.id),
            )
            updated_task = cursor.fetchone()
        conn.commit()
    return updated_task


@app.delete(
    "/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a task"
)
def delete_task(task_id: int, user: CurrentUser):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM tasks WHERE id = %s AND user_id = %s RETURNING id",
                (task_id, user.id),
            )
            deleted = cursor.fetchone()
        conn.commit()

    if deleted is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": f"Task {task_id} not found"},
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)

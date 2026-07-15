from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator


app = FastAPI(
    title="Task Management API",
    version="1.0.0",
    description="A RESTful in-memory task management API built with FastAPI.",
)

# In-memory task storage. Tasks are intentionally not persisted to a database or file.
tasks: list[dict[str, Any]] = []
next_task_id = 1


class ErrorResponse(BaseModel):
    """Standard JSON error response."""

    error: str


class Task(BaseModel):
    """Task response model."""

    id: int = Field(..., description="Unique task identifier", examples=[1])
    title: str = Field(..., description="Task title", examples=["Buy groceries"])
    done: bool = Field(..., description="Whether the task is complete", examples=[False])


class CreateTask(BaseModel):
    """Request model for creating a task."""

    title: str = Field(..., description="Task title", examples=["Buy groceries"])

    @field_validator("title")
    @classmethod
    def title_must_not_be_empty(cls, title: str) -> str:
        if not title.strip():
            raise ValueError("Title is required and cannot be empty")
        return title


class UpdateTask(BaseModel):
    """Request model for updating a task."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., description="Updated task title", examples=["Buy groceries"])
    done: bool = Field(..., description="Updated completion status", examples=[True])

    @field_validator("title")
    @classmethod
    def title_must_not_be_empty(cls, title: str) -> str:
        if not title.strip():
            raise ValueError("Title cannot be empty")
        return title


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Return HTTP errors with a simple JSON error message."""

    if isinstance(exc.detail, dict) and "error" in exc.detail:
        content = exc.detail
    else:
        content = {"error": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return validation errors as HTTP 400 responses instead of FastAPI's default 422."""

    errors = exc.errors()
    message = errors[0]["msg"] if errors else "Invalid input"
    if message.startswith("Value error, "):
        message = message.removeprefix("Value error, ")
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"error": message})


@app.get(
    "/",
    summary="Get API information",
    description="Return the API name, version, and list of available endpoints.",
)
def root() -> dict[str, Any]:
    # Provide a concise overview of this API and its routes.
    return {
        "name": "Task Management API",
        "version": app.version,
        "endpoints": {
            "GET /": "API information",
            "GET /health": "Health check",
            "GET /tasks": "List all tasks",
            "GET /tasks/{task_id}": "Get a task by ID",
            "POST /tasks": "Create a task",
            "PUT /tasks/{task_id}": "Update a task",
            "DELETE /tasks/{task_id}": "Delete a task",
            "GET /docs": "Interactive Swagger UI documentation",
        },
    }


@app.get(
    "/health",
    summary="Health check",
    description="Return a simple status response confirming that the API is running.",
)
def health() -> dict[str, str]:
    # Confirm the service is available.
    return {"status": "ok"}


@app.get(
    "/tasks",
    response_model=list[Task],
    summary="List tasks",
    description="Return the complete list of tasks stored in memory.",
)
def get_tasks() -> list[dict[str, Any]]:
    # Return all tasks currently held in the in-memory list.
    return tasks


@app.get(
    "/tasks/{task_id}",
    response_model=Task,
    responses={404: {"model": ErrorResponse, "description": "Task not found"}},
    summary="Get task by ID",
    description="Return a single task matching the provided task ID.",
)
def get_task(task_id: int) -> dict[str, Any]:
    # Find and return the requested task, or report that it does not exist.
    for task in tasks:
        if task["id"] == task_id:
            return task
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "Task not found"})


@app.post(
    "/tasks",
    response_model=Task,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse, "description": "Invalid input"}},
    summary="Create task",
    description="Create a new task with an automatically assigned ID and done set to false.",
)
def create_task(task: CreateTask) -> dict[str, Any]:
    # Add a new task to the in-memory list using the next available ID.
    global next_task_id
    new_task = {"id": next_task_id, "title": task.title, "done": False}
    tasks.append(new_task)
    next_task_id += 1
    return new_task


@app.put(
    "/tasks/{task_id}",
    response_model=Task,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid input"},
        404: {"model": ErrorResponse, "description": "Task not found"},
    },
    summary="Update task",
    description="Update the title and completion status for an existing task.",
)
def update_task(task_id: int, update: UpdateTask) -> dict[str, Any]:
    # Replace the editable fields on the requested task.
    for task in tasks:
        if task["id"] == task_id:
            task["title"] = update.title
            task["done"] = update.done
            return task
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "Task not found"})


@app.delete(
    "/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse, "description": "Task not found"}},
    summary="Delete task",
    description="Delete an existing task by ID and return no response body.",
)
def delete_task(task_id: int) -> Response:
    # Remove the requested task from the in-memory list.
    for index, task in enumerate(tasks):
        if task["id"] == task_id:
            tasks.pop(index)
            return Response(status_code=status.HTTP_204_NO_CONTENT)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "Task not found"})

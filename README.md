# Task API

A simple CRUD API for managing a to-do list, built with FastAPI. Tasks are stored in memory (no database yet).

## What this is

This API lets you create, read, update, and delete tasks (the four CRUD operations) over HTTP. It was built as part of the FlyRank Backend Internship, Week 2 assignment.

## How to install & run

1. Install dependencies:
```bash
   pip install fastapi uvicorn
```
2. Run the server:
```bash
   uvicorn main:app --reload
```
3. Open your browser to `http://localhost:8000` to confirm it's running, or `http://localhost:8000/docs` for interactive API docs.

## Endpoints

| Method | Path            | Description                     |
|--------|-----------------|---------------------------------|
| GET    | `/`             | API info                        |
| GET    | `/health`       | Health check                    |
| GET    | `/tasks`        | List all tasks                  |
| GET    | `/tasks/{id}`   | Get a single task by ID         |
| POST   | `/tasks`        | Create a new task               |
| PUT    | `/tasks/{id}`   | Update a task's title/done      |
| DELETE | `/tasks/{id}`   | Delete a task                   |

## Example request

```bash
curl -i -X POST http://localhost:8000/tasks -H "Content-Type: application/json" -d '{"title":"Buy milk"}'
```

**Response:**
```
HTTP/1.1 201 Created
date: Wed, 15 Jul 2026 10:30:00 GMT
server: uvicorn
content-length: 46
content-type: application/json

{"id":4,"title":"Buy milk","done":false}
```


## Swagger UI

The interactive API documentation is available at **`/docs`** once the server is running.

Below are screenshots of the Swagger UI demonstrating the available endpoints and CRUD operations.

### Screenshot 1
![Swagger UI Screenshot 1](<Step 5 Swagger UI_pages-to-jpg-0001.jpg>)

### Screenshot 2
![Swagger UI Screenshot 2](<Step 5 Swagger UI_pages-to-jpg-0002.jpg>)

### Screenshot 3
![Swagger UI Screenshot 3](<Step 5 Swagger UI_pages-to-jpg-0003.jpg>)

### Screenshot 4
![Swagger UI Screenshot 4](<Step 5 Swagger UI_pages-to-jpg-0004.jpg>)

### Screenshot 5
![Swagger UI Screenshot 5](<Step 5 Swagger UI_pages-to-jpg-0005.jpg>)

### Screenshot 6
![Swagger UI Screenshot 6](<Step 5 Swagger UI_pages-to-jpg-0006.jpg>)

### Screenshot 7
![Swagger UI Screenshot 7](<Step 5 Swagger UI_pages-to-jpg-0007.jpg>)

### Screenshot 8
![Swagger UI Screenshot 8](<Step 5 Swagger UI_pages-to-jpg-0008.jpg>)

### Screenshot 9
![Swagger UI Screenshot 9](<Step 5 Swagger UI_pages-to-jpg-0009.jpg>)

## Database

This project now stores tasks in **SQLite** instead of an in-memory list.

**Why SQLite:** it's a single file with zero setup — no server to install or configure — and it survives restarts, unlike the in-memory list used in Assignment 1.

**Where it lives:** `tasks.db`, created automatically the first time the app runs. It's git-ignored, so each fresh clone starts with a clean database.

**Run it:**
```bash
pip install fastapi uvicorn
uvicorn main:app --reload
```
On first run, `tasks.db` is created automatically with the `tasks` table and 3 seeded example tasks.

**Exploring the database by hand:**
Since I worked in a browser-based Codespace, I used the SQLite CLI instead of DB Browser:
```bash
sqlite3 tasks.db
```
Example query run:
```sql
SELECT COUNT(*) FROM tasks;
```
This returned `3`, confirming the table held exactly the 3 seeded tasks before I explored `UPDATE`/`DELETE` behavior.

![SQLite CLI screenshot](./sqlite-cli-screenshot.png)

![SQLite CLI screenshot](./image.png)

*Viewed using a browser-based SQLite viewer in Codespaces, showing the `tasks` table with 3 seeded rows.*

![SQLite CLI screenshot](./sqlite-db-view.png)

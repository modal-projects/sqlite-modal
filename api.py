# Notes HTTP app — mounted in-process on SqliteDatabase.web (local sqlite3, no .remote).
# Modal routes to a writer with Class parameter `db_name` on the URL.

import sqlite3

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field


def create_notes_app(*, db_name: str, conn: sqlite3.Connection) -> FastAPI:
    api = FastAPI(title=f"Notes ({db_name})")

    class NoteIn(BaseModel):
        body: str = Field(min_length=1, max_length=500)

    class Note(BaseModel):
        id: int
        body: str

    @api.get("/health")
    async def health():
        return {"ok": True, "db_name": db_name}

    @api.get("/ready")
    async def ready():
        conn.execute("SELECT 1")
        return {"ready": True, "db_name": db_name}

    @api.get("/notes", response_model=list[Note])
    async def list_notes(
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ):
        rows = conn.execute(
            "SELECT id, body FROM note ORDER BY id LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [dict(row) for row in rows]

    @api.post("/notes", response_model=Note, status_code=201)
    async def create_note(payload: NoteIn):
        try:
            cur = conn.execute("INSERT INTO note (body) VALUES (?)", (payload.body,))
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            raise HTTPException(500, str(e)) from e
        return Note(id=cur.lastrowid, body=payload.body)

    @api.post("/notes/bulk", response_model=dict, status_code=201)
    async def create_notes_bulk(payload: list[NoteIn]):
        if not payload:
            raise HTTPException(400, "empty list")
        if len(payload) > 1000:
            raise HTTPException(400, "max 1000 notes per request")
        try:
            conn.executemany(
                "INSERT INTO note (body) VALUES (?)",
                [(n.body,) for n in payload],
            )
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            raise HTTPException(500, str(e)) from e
        return {"inserted": len(payload)}

    @api.get("/notes/{note_id}", response_model=Note)
    async def get_note(note_id: int):
        row = conn.execute(
            "SELECT id, body FROM note WHERE id = ?", (note_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "note not found")
        return dict(row)

    @api.put("/notes/{note_id}", response_model=Note)
    async def update_note(note_id: int, payload: NoteIn):
        try:
            cur = conn.execute(
                "UPDATE note SET body = ? WHERE id = ?",
                (payload.body, note_id),
            )
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            raise HTTPException(500, str(e)) from e
        if cur.rowcount == 0:
            raise HTTPException(404, "note not found")
        return Note(id=note_id, body=payload.body)

    @api.delete("/notes/{note_id}", status_code=204)
    async def delete_note(note_id: int):
        try:
            cur = conn.execute("DELETE FROM note WHERE id = ?", (note_id,))
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            raise HTTPException(500, str(e)) from e
        if cur.rowcount == 0:
            raise HTTPException(404, "note not found")

    return api

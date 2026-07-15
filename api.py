# ---
# cmd: ["modal", "serve", "api.py"]
# deploy: true
# ---
#
# Example Notes HTTP API. Scales out; each request Class-RPCs into SqliteDatabase.

import modal
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from sqlite import NAME_RE, PLACEMENT, SqliteDatabase, app


@app.function(timeout=5 * 60, **PLACEMENT)
@modal.concurrent(max_inputs=100)
@modal.asgi_app()
def web():
    api = FastAPI(title="Notes")

    class NoteIn(BaseModel):
        body: str = Field(min_length=1, max_length=500)

    class Note(BaseModel):
        id: int
        body: str

    def db(tenant_id: str) -> SqliteDatabase:
        name = f"tenant-{tenant_id}"
        if not NAME_RE.fullmatch(name):
            raise HTTPException(400, f"invalid tenant_id {tenant_id!r}")
        return SqliteDatabase(db_name=name)

    @api.get("/health")
    async def health():
        return {"ok": True}

    @api.get("/t/{tenant_id}/ready")
    async def ready(tenant_id: str):
        await db(tenant_id).query.remote.aio("SELECT 1 AS ok")
        return {"ready": True, "tenant_id": tenant_id}

    @api.get("/t/{tenant_id}/notes", response_model=list[Note])
    async def list_notes(
        tenant_id: str,
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ):
        return await db(tenant_id).query.remote.aio(
            "SELECT id, body FROM note ORDER BY id LIMIT ? OFFSET ?",
            (limit, offset),
        )

    @api.post("/t/{tenant_id}/notes", response_model=Note, status_code=201)
    async def create_note(tenant_id: str, payload: NoteIn):
        out = await db(tenant_id).execute.remote.aio(
            "INSERT INTO note (body) VALUES (?)", (payload.body,)
        )
        return Note(id=out["lastrowid"], body=payload.body)

    @api.post("/t/{tenant_id}/notes/bulk", response_model=dict, status_code=201)
    async def create_notes_bulk(tenant_id: str, payload: list[NoteIn]):
        if not payload:
            raise HTTPException(400, "empty list")
        if len(payload) > 1000:
            raise HTTPException(400, "max 1000 notes per request")
        await db(tenant_id).executemany.remote.aio(
            "INSERT INTO note (body) VALUES (?)",
            [(n.body,) for n in payload],
        )
        return {"inserted": len(payload)}

    @api.get("/t/{tenant_id}/notes/{note_id}", response_model=Note)
    async def get_note(tenant_id: str, note_id: int):
        rows = await db(tenant_id).query.remote.aio(
            "SELECT id, body FROM note WHERE id = ?", (note_id,)
        )
        if not rows:
            raise HTTPException(404, "note not found")
        return Note(**rows[0])

    @api.put("/t/{tenant_id}/notes/{note_id}", response_model=Note)
    async def update_note(tenant_id: str, note_id: int, payload: NoteIn):
        out = await db(tenant_id).execute.remote.aio(
            "UPDATE note SET body = ? WHERE id = ?",
            (payload.body, note_id),
        )
        if out["rowcount"] == 0:
            raise HTTPException(404, "note not found")
        return Note(id=note_id, body=payload.body)

    @api.delete("/t/{tenant_id}/notes/{note_id}", status_code=204)
    async def delete_note(tenant_id: str, note_id: int):
        out = await db(tenant_id).execute.remote.aio(
            "DELETE FROM note WHERE id = ?", (note_id,)
        )
        if out["rowcount"] == 0:
            raise HTTPException(404, "note not found")

    return api

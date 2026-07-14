# ---
# cmd: ["modal", "serve", "api.py"]
# deploy: true
# ---

# # Notes API — DB per tenant via Modal RPC
#
# ```bash
# uv sync
# uv run modal serve api.py
# curl -X POST "$URL/t/acme/notes" -H 'content-type: application/json' \
#   -d '{"body":"hello"}'
# ```

from typing import Annotated

from fastapi import FastAPI, HTTPException, Path
from pydantic import BaseModel, Field

import modal
from sqlite import SqliteDatabase, app

TenantId = Annotated[
    str,
    Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
]


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=500)


class Note(BaseModel):
    id: int
    body: str


@app.function(timeout=60, max_containers=50)
@modal.asgi_app()
def api():
    web = FastAPI(title="Notes")

    @web.get("/health")
    async def health():
        return {"ok": True}

    @web.get("/ready")
    async def ready():
        await SqliteDatabase(db_name="tenant-ready").query.remote.aio("SELECT 1 AS ok")
        return {"ready": True}

    @web.get("/t/{tenant_id}/notes", response_model=list[Note])
    async def list_notes(tenant_id: TenantId):
        db = SqliteDatabase(db_name=f"tenant-{tenant_id}")
        return await db.query.remote.aio("SELECT id, body FROM note ORDER BY id")

    @web.post("/t/{tenant_id}/notes", response_model=Note, status_code=201)
    async def create_note(tenant_id: TenantId, payload: NoteIn):
        db = SqliteDatabase(db_name=f"tenant-{tenant_id}")
        result = await db.execute.remote.aio(
            "INSERT INTO note (body) VALUES (?)", (payload.body,)
        )
        return Note(id=result["lastrowid"], body=payload.body)

    @web.get("/t/{tenant_id}/notes/{note_id}", response_model=Note)
    async def get_note(tenant_id: TenantId, note_id: int):
        db = SqliteDatabase(db_name=f"tenant-{tenant_id}")
        rows = await db.query.remote.aio(
            "SELECT id, body FROM note WHERE id = ?", (note_id,)
        )
        if not rows:
            raise HTTPException(404, "note not found")
        return rows[0]

    @web.put("/t/{tenant_id}/notes/{note_id}", response_model=Note)
    async def update_note(tenant_id: TenantId, note_id: int, payload: NoteIn):
        db = SqliteDatabase(db_name=f"tenant-{tenant_id}")
        result = await db.execute.remote.aio(
            "UPDATE note SET body = ? WHERE id = ?", (payload.body, note_id)
        )
        if result["rowcount"] == 0:
            raise HTTPException(404, "note not found")
        return Note(id=note_id, body=payload.body)

    @web.delete("/t/{tenant_id}/notes/{note_id}", status_code=204)
    async def delete_note(tenant_id: TenantId, note_id: int):
        db = SqliteDatabase(db_name=f"tenant-{tenant_id}")
        result = await db.execute.remote.aio(
            "DELETE FROM note WHERE id = ?", (note_id,)
        )
        if result["rowcount"] == 0:
            raise HTTPException(404, "note not found")

    return web

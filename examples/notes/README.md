# Notes example

Single Sqlite: schema + `executemany` + query + `flush`.

```bash
uv sync
export MODAL_PROXY_TOKEN_ID=wk-…   # proxy tokens, not API tokens
export MODAL_PROXY_TOKEN_SECRET=ws-…
modal workspace proxy-tokens allow "$MODAL_PROXY_TOKEN_ID" main

uv run modal run examples/notes/app.py
# or: uv run modal serve examples/notes/app.py
```

`Sqlite.from_name("notes")` → `attach(..., min_containers=1)` → SQL over HTTP.

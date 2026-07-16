# Notes example

Single-DB smoke for onboarding: schema → `executemany` → query → `flush`.

## Setup

Proxy tokens (`wk-` / `ws-`), then:

```bash
uv sync
export MODAL_PROXY_TOKEN_ID=wk-…
export MODAL_PROXY_TOKEN_SECRET=ws-…
modal workspace proxy-tokens allow "$MODAL_PROXY_TOKEN_ID" main
```

## Run

```bash
uv run modal run examples/notes/app.py
# live-reload: uv run modal serve examples/notes/app.py
```

`Sqlite.from_name("notes")` attaches with `min_containers=1` in `eu-west` / `aws`.

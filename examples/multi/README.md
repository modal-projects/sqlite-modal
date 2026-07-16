# Multi-DB example

Two named Sqlites on one App (`alpha`, `beta`) — separate Servers and Volumes.

```bash
uv sync
export MODAL_PROXY_TOKEN_ID=wk-…
export MODAL_PROXY_TOKEN_SECRET=ws-…
modal workspace proxy-tokens allow "$MODAL_PROXY_TOKEN_ID" main

uv run modal run examples/multi/app.py
```

Each name gets `SqliteServer_{name}` and Volume `{name}-data`.

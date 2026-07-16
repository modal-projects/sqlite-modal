# Multi-DB example

Shows two named Sqlites on one App — separate Servers and Volumes.

## Setup

Same proxy-token env as the notes example.

## Run

```bash
uv run modal run examples/multi/app.py
```

Creates `SqliteServer_alpha` / `SqliteServer_beta` and Volumes `alpha-data` /
`beta-data`. Each inserts and queries independently.

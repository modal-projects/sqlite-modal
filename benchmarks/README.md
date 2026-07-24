# Benchmarks

```bash
uv run python benchmarks/app.py
uv run python benchmarks/profile.py
```

Both create their demo DBs with `Sqlite.from_name(..., create_if_missing=True)`.

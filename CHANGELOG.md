# Changelog

## 0.2.0

### Added

- `Sqlite.from_name` / `connect` with local pyturso `push` / `pull`.
- Per-name Modal App (`sqlite-modal-{name}`) running `tursodb --sync-server`.
- Per-name Volume (`sqlite-modal-{name}-data`) restore/save of `server.db*` on Server enter/exit.
- Notes and multi-DB examples; local latency / throughput benches.

### Changed

- Replaced the earlier HTTP SQL Server stack with Turso Sync on Modal Server.
- Image installs `tursodb` from the versioned tarball and checks SHA-256.
- CI is `contents: read` and pins `actions/checkout` / `astral-sh/setup-uv` to commit SHAs.
- CI runs on GitHub-hosted `ubuntu-latest`.
- Docs and examples no longer recommend `max_containers=1`.

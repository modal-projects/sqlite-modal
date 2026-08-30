# Changelog

## 0.2.0

### Added

- `Sqlite.from_name` / `connect` with local pyturso `push` / `pull`.
- Per-name Modal App (`sqlite-modal-{name}`) running `tursodb --sync-server`.
- Volume restore/save of `server.db*` on Server enter/exit.
- Notes and multi-DB examples; local latency / throughput benches.

### Changed

- Replaced the earlier HTTP SQL Server stack with Turso Sync on Modal Server.

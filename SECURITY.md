# Security

`sqlite-modal` is an operator-deployed library. You create named databases
in your Modal workspace. This is not a managed multi-tenant service.

## Sync URL

Each name deploys a Modal Server with `unauthenticated=True` so pyturso
can `push` / `pull`. Anyone who has the URL can read and write that
database. Treat the URL as a capability. Do not share it.

## Shared Volume

All names in a workspace share one Volume (`sqlite-modal-data`), with
one directory per name. `push` conflicts are last-push-wins.

`server.db*` is copied to the Volume when the Server exits. A crash
before exit can lose data that was only in the hot file.

Prefer `max_containers=1` so two writers do not race the same primary.

## CI runners

Repo CI runs on a [runner-modal](https://github.com/modal-projects/runner-modal)
pool you deploy (`runners/`). Self-hosted Jobs execute workflow steps with
`GITHUB_TOKEN` in the Sandbox. When this repo is public, require approval
for outside collaborators and read-only default workflow permissions.

## Reporting issues

Please use [GitHub Security Advisories](https://github.com/modal-projects/sqlite-modal/security/advisories/new)
for this repository. Do not open public issues for undisclosed
vulnerabilities.

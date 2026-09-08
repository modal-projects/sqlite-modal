# Security

`sqlite-modal` is an operator-deployed library. You create named databases
in your Modal workspace. This is not a managed multi-tenant service.

## Sync URL

Each name deploys a Modal Server with `unauthenticated=True` so pyturso
can `push` / `pull`. Anyone who has the URL can read and write that
database. Treat the URL as a capability. Do not share it.

## Volume

Each name gets its own Volume (`sqlite-modal-{name}-data`). `push`
conflicts on that name are last-push-wins.

`server.db*` is copied to the Volume when the Server exits. A crash
before exit can lose data that was only in the hot file.

Prefer `max_containers=1` so two writers do not race the same primary.

## CI

Repo CI runs on GitHub-hosted `ubuntu-latest`. The workflow grants
`contents: read` only and pins `actions/checkout` / `astral-sh/setup-uv`
to commit SHAs.

## Reporting issues

Please use [GitHub Security Advisories](https://github.com/modal-projects/sqlite-modal/security/advisories/new)
for this repository. Do not open public issues for undisclosed
vulnerabilities.

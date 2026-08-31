# Modal CI runners

Self-hosted GitHub Actions for this repo via
[runner-modal](https://github.com/modal-projects/runner-modal):
`workflow_job` webhook → ephemeral Modal Sandbox → one-shot JIT runner.

You deploy the pool in your Modal workspace. This is not a managed
multi-tenant service.

## Pool

| Pool | App | Labels | Jobs |
|------|-----|--------|------|
| `ci` | `sqlite-modal-ci` | `self-hosted, modal, ci` | `.github/workflows/ci.yml` |

One App per pool. The workflow pin
`job-${{ github.run_id }}-${{ github.job }}` makes each JIT runner claimed
by exactly one job.

## One-time setup

1. Fine-grained PAT (or GitHub App) that can call
   `POST /repos/modal-projects/sqlite-modal/actions/runners/generate-jitconfig`
   (Administration: Read & write).
2. Split Secrets. Never merge these.

   ```bash
   modal secret create github-token GITHUB_TOKEN=ghp_xxx
   modal secret create github-webhook WEBHOOK_SECRET=$(openssl rand -hex 32)
   ```

3. Deploy:

   ```bash
   uv sync
   uv run modal deploy cpu_app.py
   ```

4. Repo webhook, events = **Workflow jobs** only, content type JSON:

   ```bash
   uv run python -c "from runner_modal import Runner; print(Runner.from_name('ci').url)"
   ```

   Payload URL is `{url}/github`. Secret is the same `WEBHOOK_SECRET`.

5. When the repo is public: require approval for outside collaborators and
   read-only default workflow permissions.

## Ops

| Task | Command |
|------|---------|
| Health | `curl -sS "$URL/health"` |
| Webhook logs | `modal app logs sqlite-modal-ci` |
| Teardown pool | `uv run python -c "from runner_modal import Runner; Runner.objects.delete('ci')"` |
| Stop App | `modal app stop sqlite-modal-ci` then remove the repo webhook |

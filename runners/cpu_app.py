"""CPU CI pool for sqlite-modal.

    modal secret create github-token GITHUB_TOKEN=ghp_xxx
    modal secret create github-webhook WEBHOOK_SECRET=$(openssl rand -hex 32)
    uv run modal deploy cpu_app.py

Webhook: {Runner.from_name("ci").url}/github
Events: Workflow jobs only.
"""

from __future__ import annotations

import modal
from runner_modal import Runner

app = modal.App("sqlite-modal-ci")
github = modal.Secret.from_name("github-token", required_keys=["GITHUB_TOKEN"])
webhook = modal.Secret.from_name("github-webhook", required_keys=["WEBHOOK_SECRET"])

Runner.create(
    app=app,
    name="ci",
    github_secret=github,
    webhook_secret=webhook,
    repositories=["modal-projects/sqlite-modal"],
    labels=["self-hosted", "modal", "ci"],
    region="us-east",
    cpu=2.0,
    memory=4096,
    max_concurrent=8,
    min_containers=0,
    idle_timeout=900,
)

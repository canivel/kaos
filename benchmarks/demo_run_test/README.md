# demo_run_test — Full Engagement Reproduction

This folder reproduces the full payment-platform engagement walkthrough
shown at https://canivel.github.io/kaos/blog/kaos-full-engagement.html
in a clean, isolated directory. Use it to verify that every CLI command
shown in the blog runs against a real database with real output.

## Reproduce

```bash
cd demo_run_test
uv run kaos init --db payments-demo.db
uv run python seed_payments_demo.py
```

Then run any of the commands from the blog:

```bash
export KAOS_DB=payments-demo.db

uv run kaos ls
uv run kaos skills search "payments fastapi"
uv run kaos skills search "fraud detection"
uv run kaos skills search "terraform kubernetes"
uv run kaos skills search "zero downtime migration"
uv run kaos skills search "compliance"
uv run kaos skills ls
uv run kaos memory search "Feast cold start"
uv run kaos memory search "PCI DSS"
uv run kaos memory search "load test"
```

All 11 commands return real JSON output from the seeded database.

## What gets seeded

- 13 agents (4 waves: research/architect → 6 builders → 3 QA → 2 deploy)
- 6 skills in the SkillStore (`fastapi-payment-gateway`, `gke-terraform-microservices`, `pci-dss-v4-fastapi-postgres`, `fraud-detection-gbm-pipeline`, `zero-downtime-parallel-run-migration`, `datadog-slo-alerting-pack`)
- 5 memory entries in the MemoryStore (cold-start fix, PCI-DSS automation, security findings, Terraform GKE infra, load test results)

The seed uses `Kaos.spawn()`, `SkillStore.save()`, and `MemoryStore.write()` —
the exact same API surface any KAOS agent uses at runtime.

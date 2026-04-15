"""Seed demo-engagement.db with a realistic payment-platform engagement."""
import os
import sqlite3

DB = "demo-engagement.db"
if os.path.exists(DB):
    os.remove(DB)

from kaos import Kaos
from kaos.memory import MemoryStore
from kaos.skills import SkillStore

db = Kaos(DB)

# ── Spawn agents in wave order ──────────────────────────────────────────────
agents = {}
wave1 = ["research-agent", "architect-agent"]
wave2 = ["payment-engine-agent", "fraud-agent", "api-gateway-agent",
         "compliance-agent", "infra-agent", "test-agent"]
wave3 = ["security-agent", "perf-agent", "compliance-validator"]
wave4 = ["deploy-agent", "observability-agent"]

for name in wave1 + wave2 + wave3 + wave4:
    aid = db.spawn(name)
    agents[name] = aid

# Set statuses via direct SQL (spawn creates 'initialized')
conn = sqlite3.connect(DB)
for name in wave1 + wave2 + wave3 + wave4:
    conn.execute("UPDATE agents SET status='completed' WHERE agent_id=?", (agents[name],))
conn.commit()

# ── Write skills ─────────────────────────────────────────────────────────
skills = SkillStore(conn)

skills.save(
    name="fastapi-payment-gateway",
    description="FastAPI REST gateway with idempotent payment handling, webhook delivery, "
                "exponential retry, dead-letter queue, and OpenAPI spec generation.",
    template="Build a FastAPI payment gateway for {project}. Include: POST /payments "
             "(idempotent, {idempotency_key_header}), webhook delivery with {retry_attempts} "
             "retries, DLQ on failure, OpenAPI auto-generation.",
    source_agent_id=agents["api-gateway-agent"],
    tags=["fastapi", "payments", "webhooks", "idempotent"],
)

skills.save(
    name="gke-terraform-microservices",
    description="Terraform modules for GKE: VPC, Cloud SQL (Postgres), Redis, Kafka, "
                "Helm releases, HPA + PDB configs, Datadog integration.",
    template="Provision GKE infrastructure for {project} using Terraform. Modules: "
             "gke-cluster, cloud-sql-{db_engine}, redis, kafka, helm-releases. "
             "Enable HPA with target CPU {hpa_target_cpu}%.",
    source_agent_id=agents["infra-agent"],
    tags=["gke", "terraform", "kubernetes", "payments", "infrastructure"],
)

skills.save(
    name="pci-dss-v4-fastapi-postgres",
    description="Automated PCI-DSS v4.0 evidence collection for FastAPI + Postgres stacks. "
                "All 12 requirements mapped to code assertions. Generates audit-ready PDF/CSV.",
    template="Add PCI-DSS v4.0 compliance automation to {project}. Map all 12 requirements "
             "to automated checks on {stack}. Generate quarterly evidence report.",
    source_agent_id=agents["compliance-agent"],
    tags=["pci-dss", "compliance", "security", "fastapi", "postgres"],
)

skills.save(
    name="fraud-detection-gbm-pipeline",
    description="Gradient-boosted fraud detection with Feast feature store, SHAP explainability, "
                "cold-start fallback (global percentile prior), scheduled retraining.",
    template="Build fraud detection for {project}: GBM classifier on {num_features} features, "
             "Feast online store integration, SHAP explainability per transaction, "
             "cold-start fallback via global risk percentile, retrain on {retrain_schedule}.",
    source_agent_id=agents["fraud-agent"],
    tags=["fraud", "ml", "gbm", "feast", "payments", "shap"],
)

skills.save(
    name="zero-downtime-parallel-run-migration",
    description="Dual-write parallel-run router for zero-downtime monolith cutover. "
                "Result diffing, per-cohort feature flags, automatic rollback on drift.",
    template="Migrate {project} from {legacy_system} using parallel-run strategy. "
             "Dual-write for {parallel_run_days} days, diff tolerance {diff_threshold}%, "
             "per-client feature flags, auto-rollback trigger.",
    source_agent_id=agents["payment-engine-agent"],
    tags=["migration", "zero-downtime", "parallel-run", "monolith", "rollback"],
)

skills.save(
    name="datadog-slo-alerting-pack",
    description="Datadog SLO definitions, alert policies, runbook templates for payment services. "
                "Covers uptime, p99 latency, fraud catch rate, queue lag.",
    template="Configure Datadog observability for {project}: SLOs (uptime {uptime_target}%, "
             "p99 < {latency_target}ms), {num_alerts} alert policies with PagerDuty, "
             "runbooks linked per alert.",
    source_agent_id=agents["observability-agent"],
    tags=["datadog", "observability", "slo", "alerting", "payments"],
)

conn.commit()

# ── Write memory entries ──────────────────────────────────────────────────
mem = MemoryStore(conn)

mem.write(
    agents["fraud-agent"],
    "Feast cold-start fix: when online store has no features for a new merchant_id, "
    "GBM scorer receives null vector causing NaN propagation and scoring crash. "
    "Fix: inject global merchant risk percentile (p50) as prior. AUC impact: none at p95. "
    "Applied iteration 3, resolved in 18s by SurrogateVerifier.",
    type="result",
    key="feast-cold-start-fix",
)

mem.write(
    agents["compliance-agent"],
    "PCI-DSS v4.0 all 12 requirements automated with FastAPI + Postgres. "
    "Evidence collection generates audit-ready PDF + CSV. SOC2 CC controls (61 total) "
    "mapped as code assertions. HMAC append-only audit log with integrity chain. "
    "Quarterly report generation under 90 seconds.",
    type="result",
    key="pci-dss-v4-automation",
)

mem.write(
    agents["security-agent"],
    "HSTS header missing from FastAPI middleware — also a PCI-DSS Req 4.2.1 violation. "
    "Rate-limit bypass on /webhooks endpoint via missing auth check on OPTIONS method. "
    "Both fixed in security pass. Re-scan: clean. Compliance validator notified via shared log.",
    type="result",
    key="security-pass-findings",
)

mem.write(
    agents["infra-agent"],
    "Terraform GKE modules for stateful payment workloads: 8 modules (VPC, Cloud SQL, "
    "Redis, Kafka, GKE cluster, Helm releases, Secret Manager, Datadog). "
    "47 resources on first apply, 0 destroyed. GKE node pool: n2-standard-4, "
    "min 3 / max 12 nodes. Cloud SQL Postgres 15, HA with read replica.",
    type="result",
    key="terraform-gke-payment-infra",
)

mem.write(
    agents["perf-agent"],
    "Load test result: 50,312 TPS sustained, p99 latency 187ms initially. "
    "Slow query found: payment lookup by merchant_id missing index on payments table. "
    "After adding index: p99 dropped to 141ms. Redis cache hit rate: 94.2%. "
    "Kafka consumer lag: 0 under peak load with 6 consumer replicas.",
    type="result",
    key="load-test-50k-tps",
)

conn.commit()
conn.close()
print(f"Seeded {DB} successfully.")
print(f"  Agents:  {len(agents)}")
print(f"  Skills:  6")
print(f"  Memory:  5 entries")

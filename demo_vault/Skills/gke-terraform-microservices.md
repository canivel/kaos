---
type: skill
skill_id: 2
name: gke-terraform-microservices
source_agent: "[[infra-agent]]"
use_count: 0
success_count: 0
success_rate: ""
created_at: "2026-04-15T17:12:25.690"
updated_at: "2026-04-15T17:12:25.690"
tags: [skill, gke, terraform, kubernetes, payments, infrastructure]
---

# gke-terraform-microservices

> [!kaos-skill] Terraform modules for GKE: VPC, Cloud SQL (Postgres), Redis, Kafka, Helm releases, HPA + PDB configs, Datadog integration.
> Source: [[infra-agent]]  ·  use_count: 0

## Template
```
Provision GKE infrastructure for {project} using Terraform. Modules: gke-cluster, cloud-sql-{db_engine}, redis, kafka, helm-releases. Enable HPA with target CPU {hpa_target_cpu}%.
```

## Applied by
_(no recorded applications yet)_
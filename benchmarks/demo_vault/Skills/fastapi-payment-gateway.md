---
type: skill
skill_id: 1
name: fastapi-payment-gateway
source_agent: "[[api-gateway-agent]]"
use_count: 0
success_count: 0
success_rate: ""
created_at: "2026-04-15T17:12:25.657"
updated_at: "2026-04-15T17:12:25.657"
tags: [skill, fastapi, payments, webhooks, idempotent]
---

# fastapi-payment-gateway

> [!kaos-skill] FastAPI REST gateway with idempotent payment handling, webhook delivery, exponential retry, dead-letter queue, and OpenAPI spec generation.
> Source: [[api-gateway-agent]]  ·  use_count: 0

## Template
```
Build a FastAPI payment gateway for {project}. Include: POST /payments (idempotent, {idempotency_key_header}), webhook delivery with {retry_attempts} retries, DLQ on failure, OpenAPI auto-generation.
```

## Applied by
_(no recorded applications yet)_
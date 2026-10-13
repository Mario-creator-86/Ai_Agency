# Observability Metrics Catalog

## System

- API availability;
- DB latency/errors;
- worker count;
- scheduler heartbeat;
- CPU/memory;
- disk/object storage;
- backup age.

## Workflow

- runs started/completed/failed;
- duration;
- stage duration;
- queue age;
- stuck count;
- retry count;
- rework cycles;
- repair queue age.

## Providers

- health;
- auth state;
- latency p50/p95;
- error rate;
- 429 rate;
- cost;
- model availability;
- role suitability.

## Agent

- task success;
- schema failure;
- QC rejection;
- cost;
- latency;
- current concurrency;
- benchmark delta.

## Content

- research source count/quality;
- unsupported claim rate;
- novelty score;
- QC failures by type;
- render retries;
- character drift.

## Publishing

- intents;
- confirmed remote IDs;
- reconciliation age;
- duplicate-attempt prevention count;
- quota remaining where available.

## UI/Event

- outbox lag;
- WebSocket active clients;
- event replay count;
- projection lag;
- snapshot mismatch count.

## Business

- production cost/video;
- manual interventions;
- mature analytics by channel;
- actual vs estimated revenue when available.

## Alert principles

Alert on actionable conditions, not every transient retry.


## V4 organizational metrics

- active agents by department;
- manager span of control;
- idle-agent ratio;
- coordination messages/task;
- department throughput;
- department cost;
- department error/rework;
- campaign publish success;
- social adapter health;
- marketing conversion/confidence;
- moderation queue;
- compliance holds;
- company events scheduled/active;
- production days lost to events;
- event-day story performance.


# V5 Financial Metrics

- `vr_treasury_available`
- `vr_treasury_reserved`
- `vr_revenue_settled_daily`
- `vr_revenue_reversed_daily`
- `vr_external_operating_cost_daily`
- `vr_virtual_procurement_spend_daily`
- `vr_debt_outstanding`
- `vr_interest_due_30d`
- `financial_runway_days`
- `forecast_mape_or_error`
- `reconciliation_backlog_count`
- `duplicate_mint_attempt_count`
- `procurement_quote_stale_count`
- `procurement_avg_savings_vs_new_market`
- `provider_cost_per_published_video`

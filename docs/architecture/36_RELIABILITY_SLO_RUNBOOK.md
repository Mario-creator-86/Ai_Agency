# Reliability SLO and Operations Runbook

## Production readiness is measured

Example configurable SLOs:
- duplicate public publication: 0;
- UI authoritative-state mismatch: 0 known unresolved;
- daily workflow start within schedule window: >= target;
- workflow completion without Owner intervention: >= target;
- P0 detection latency: <= target;
- stuck task detection: <= target;
- successful backup: >= target.

Do not choose final numeric targets until baseline exists.

## Operational indicators

- workflow success;
- queue depth/age;
- retry rate;
- circuit breakers open;
- provider health;
- outbox lag;
- WebSocket lag;
- disk;
- cost;
- unresolved repairs;
- OAuth expiry.

## Burn-in

Before full autonomous public mode:
- run supervised/dry production repeatedly;
- record every manual intervention;
- fix recurring classes;
- demonstrate restart/recovery;
- verify costs.

## Incident response

P0:
- safe mode/STOP AUTONOMY;
- preserve evidence;
- reconcile external state;
- notify Owner.

P1:
- affected subsystem paused/fallback;
- incident tracked.

## Runbook actions

Document commands/UI actions for:
- restart worker;
- restart scheduler;
- rotate credential;
- reconcile upload;
- release stuck lease;
- restore backup;
- disable provider;
- disable publishing;
- resume after incident.

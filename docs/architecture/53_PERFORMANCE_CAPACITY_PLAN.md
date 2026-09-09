# Performance and Capacity Plan

## Why

Video generation, rendering, browser research and many public viewers can load different resources.

## Resource classes

- CPU-bound: FFmpeg/render;
- memory-bound: media processing;
- network-bound: provider/API/download;
- external-concurrency-bound: video/image APIs;
- DB/event-bound: high activity;
- frontend rendering: office spectators.

## Capacity controls

Configure:
- max LLM concurrent calls;
- max browser sessions;
- max video jobs/provider;
- max FFmpeg workers;
- max uploads;
- max WebSocket fan clients per instance future.

## Priority

Production deadlines outrank:
- experiments;
- benchmarks;
- speculative idea generation.

## Storage planning

Track:
- raw media growth;
- final renders;
- temporary files;
- source snapshots;
- backups.

Estimate runway at current daily production.

## UI

Use:
- sprite atlases;
- culling;
- event batching;
- latest-state compression;
for a growing office.

## Load tests

Before public fan launch:
- spectator load;
- event burst;
- reconnect storm.

Before 2+ Shorts/day:
- media queue and cost capacity test.


## V4 org capacity

Capacity planning should include management/coordination cost.

Adding agents does not linearly increase throughput.

Track:
- queue age;
- worker capacity;
- agent concurrency;
- manager direct reports;
- cross-department handoffs;
- token/message overhead;
- social API quotas;
- moderation volume.

Create role/department only when expected net capacity/value is positive.

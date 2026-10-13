# Prompt, Context and Memory Architecture

## Purpose

LLM quality depends as much on context construction as on model choice. Prompt/context/memory must therefore be a controlled subsystem.

## PromptTemplate

Fields:
- prompt_template_id;
- role_id;
- version;
- system policy;
- task instructions;
- expected output schema;
- allowed variables;
- model-specific notes;
- status: DRAFT / TESTING / ACTIVE / RETIRED;
- created_by;
- evaluation baseline.

Never silently overwrite a prompt used in production.

## ContextManifest

Every AgentRun stores a manifest of what was supplied:
- task input;
- evidence IDs;
- memory IDs;
- previous output references;
- Owner policy version;
- strategy version;
- tool list;
- token budget.

Do not require storing hidden model scratchpad.

## Context budget

Prioritize:
1. hard policy;
2. role contract;
3. task;
4. current evidence;
5. relevant continuity/history;
6. optional examples.

When context is too large:
- summarize;
- retrieve selectively;
- omit irrelevant data.

Never truncate hard policy/evidence constraints silently.

## Memory classes

### VERIFIED_FACT
Evidence-backed factual item.

### OWNER_POLICY
Explicit Owner rule.

### STRATEGY
Current operational strategy.

### HISTORICAL_EVENT
Committed studio history.

### PROCEDURAL
Validated internal operating knowledge.

### AGENT_OPINION
Non-authoritative analysis.

### TEMP_CONTEXT
Ephemeral task context.

## Memory metadata

- source/provenance;
- created_at;
- last_verified;
- expires_at/TTL;
- confidence if applicable;
- visibility;
- invalidated_at;
- superseded_by.

## Retrieval

Memory retrieval should be:
- role-aware;
- task-aware;
- visibility-aware;
- freshness-aware.

Do not let semantic similarity alone select a stale or forbidden memory.

## Memory invalidation

Examples:
- provider capability changed;
- strategy superseded;
- factual source became stale;
- employee terminated;
- Owner policy changed.

Invalidation should not erase history; it marks memory unusable for current action.

## Prompt injection boundary

Untrusted source text is wrapped/marked as data.

Never concatenate web text into a privileged system section.

## Evaluation

Prompt changes require:
- benchmark;
- format compliance;
- quality score;
- factual adherence where relevant;
- cost/latency comparison.

Director may propose prompt changes; high-impact changes follow governance policy.

## Rollback

Every active prompt must have a known prior version and rollback operation.

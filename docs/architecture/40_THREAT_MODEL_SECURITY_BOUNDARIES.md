# Threat Model and Security Boundaries

## Assets to protect

- provider/API credentials;
- YouTube OAuth;
- Owner controls;
- publishing capability;
- budget;
- source code;
- DB/audit history;
- public reputation;
- user data future.

## Threat sources

- malicious web content;
- prompt injection;
- compromised provider response;
- malicious fan submission;
- dependency compromise;
- exposed public endpoint;
- accidental agent over-permission;
- leaked logs;
- operator mistake.

## Trust zones

### Zone A — Secrets/Policy
Highest trust.

### Zone B — Internal backend
Trusted application code.

### Zone C — Agent/model outputs
Untrusted until schema/policy validation.

### Zone D — External web/providers
Untrusted external data/effects.

### Zone E — Public users
Untrusted.

## Critical controls

- least privilege;
- tool mediation;
- egress restrictions;
- SSRF defense;
- no raw secrets in prompts;
- validation;
- rate limits;
- auth;
- audit;
- safe subprocess;
- file validation;
- dependency controls.

## LLM-specific threat

A model response may:
- claim nonexistent tool result;
- output malicious URL;
- smuggle instructions from source content;
- request excessive privileges.

Backend policy/tool layer must refuse unauthorized effect.

## Incident containment

Ability to:
- disable provider;
- revoke token;
- disable publishing;
- stop autonomy;
- enter safe mode;
- preserve logs.

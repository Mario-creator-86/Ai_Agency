# Channels and Automation v3

## Channel A — Main

English factual Shorts for a global audience.

The Director owns topic weighting but major strategic pivots can require Owner approval.

## Channel B — Office Serial

Based on yesterday's real studio events.

Separate:
- channel credentials/config;
- publication history;
- analytics;
- content IDs.

## Channel setup

The system may propose:
- name;
- description;
- tagline;
- avatar prompt;
- banner prompt;
- brand rules.

External account/channel creation may require human authentication. Do not pretend it was automated if the platform requires manual setup.

## Scheduler

Durable and timezone-aware.

Workflows:
- main daily production;
- end-of-day DailyStudioLog close;
- next-day office serial production;
- publication scheduling;
- analytics collection.

## Missed runs

Configurable policy:
- skip;
- catch up once;
- reschedule.

Never create a backlog explosion after long offline periods without policy.

## Automation rollout

1. manual topic;
2. verified script;
3. final MP4;
4. private upload;
5. non-publishing autonomous simulation;
6. supervised publishing;
7. autonomous Channel A;
8. DailyStudioLog/Showrunner;
9. supervised Channel B;
10. autonomous Channel B.

## Platform truth

YouTube state is external truth.

Store:
- remote channel ID;
- remote video ID;
- upload timestamps;
- publish status;
- API result.

If uncertain after timeout:
reconcile before retry.

## Analytics cadence

Do not treat analytics as instantly final.

Store time-series snapshots.

Growth decisions should use configurable observation windows and minimum samples.

## Channel isolation

Treat Channel A and Channel B as separate publishing domains.

Each has:
- credentials/channel ID;
- strategy;
- schedule;
- policy state;
- analytics;
- brand identity;
- content history;
- quota budget.

A failure or policy pause on one channel should not automatically corrupt the other.

## Daily preflight

Before scheduled production/publish:
- channel auth;
- quota;
- policy gate version;
- publishing enable flag;
- budget;
- required provider availability.

## Revenue truth

Views, estimated platform revenue, pending payout, settled revenue and spendable VR$ are distinct concepts.

Never derive "we earned $100" from views or forecasts alone. Only verified settlement evidence may be labeled settled revenue and become mint-eligible VR$.

## Channel deletion/private/unlisted changes

Analytics reconciler must handle:
- video removed;
- video made private;
- upload rejected;
- schedule changed externally.

Remote platform state can change outside the app.

## Content cadence safety

Director should consider:
- recent upload frequency;
- audience fatigue;
- production backlog;
- quality;
- policy/spam risk.

More videos is not automatically better.


## V4 — Distribution ecosystem

The channel strategy expands beyond two YouTube channels.

Core public communication surfaces may include:
- YouTube;
- TikTok;
- Instagram;
- Facebook;
- Telegram.

The Main Content and Office Serial remain primary produced media, while Marketing distributes:
- teasers;
- clips;
- reminders;
- polls;
- milestone posts;
- community messages.

Use cross-platform adapter architecture.

### Same-day / next-day loop

Today:
real studio event
→ Marketing teaser.

Tomorrow:
Office Serial episode
→ cross-platform promotion
→ analytics
→ CMO/CEO learning.

### Automation rollout

Do not enable full auto-posting to every platform simultaneously.

Recommended:
1. draft-only;
2. supervised;
3. one-platform autonomous;
4. multi-platform supervised;
5. multi-platform autonomous after reliability/policy burn-in.


# V5 Monetization Automation

The daily automation may ingest/read financial evidence from connected platform adapters, but must separate:
- views/engagement;
- estimated revenue;
- pending payout;
- settled payout.

Only eligible settled or Owner-confirmed events may mint spendable VR$.

Marketing may advertise paid pitches/donations only after Legal/Owner policy defines terms. Payment intake does not grant the payer authority over content gates or CEO decisions.

A paid pitch buys **review/access to the idea pipeline**, not guaranteed publication, unless Owner explicitly defines different terms.

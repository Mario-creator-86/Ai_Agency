# Marketing & Communications Department

## Purpose

Turn real studio activity and published content into sustained multi-platform audience growth without inventing events, claims or outcomes.

Marketing is a real operating department of the AI company, not a decorative social-post generator.

The department reports to the Director/CEO. It may have a CMO/Marketing Director with delegated authority.

## Initial structure

The first implementation may use a small team:

- **CMO / Marketing Director**
- **Social Media Manager**
- **Community Manager**
- **Marketing Analytics Agent**

The Director may later create or hire specialist roles when evidence justifies them:

- Teaser / Hook Copywriter
- Competitive Marketing Scout
- TikTok Specialist
- Instagram Specialist
- YouTube Growth Specialist
- Facebook Specialist
- Telegram Community Agent
- Paid Media Specialist
- Brand Manager
- Reputation / Crisis Communications Agent
- Partnership / Sponsorship Manager
- Meme / Creative Social Agent

The organization must remain dynamic. These roles are examples, not a hardcoded permanent list.

## Channels

Design adapters/configuration for:

- YouTube
- TikTok
- Instagram
- Facebook
- Telegram

Each channel/account has its own:
- credentials/auth status;
- capabilities;
- publishing limits;
- account ID;
- audience;
- content formats;
- analytics support;
- moderation support;
- rate limits;
- policy status.

Never claim posting/analytics functionality that the platform integration does not actually support.

## Same-day teaser → next-day episode workflow

A key marketing loop is:

`Real Studio Event`
→ event committed in backend
→ sanitizer / public-safety check
→ Teaser Opportunity
→ CMO selects/declines
→ copy variants
→ truth/continuity gate
→ platform adaptation
→ schedule/publish
→ next-day office episode
→ attribution/analytics.

Example real event:

- Director raises a serious complaint to Security Agent because a task was missed.

Possible truthful teaser:

> "Security missed something important today, and the Director was not happy. Tomorrow: the full office episode."

Not allowed:
- say the Security Agent was fired if it was not fired;
- invent an incident;
- reveal secret/security details;
- promise an episode if the pipeline has no committed/scheduled episode and the policy requires certainty.

## Curiosity marketing / clickbait policy

The studio may optimize for curiosity, urgency and emotional hooks, but must use **truthful curiosity gaps**, not deceptive clickbait.

A marketing hook must pass:
- Event Grounding Gate
- Public Safety/Sanitization Gate
- Narrative Continuity Gate
- Brand Safety Gate
- Platform Policy Gate
- Rights/Legal Gate where needed.

Score possible variants on:
- curiosity;
- clarity;
- expected retention;
- emotional salience;
- factual fidelity;
- payoff alignment;
- platform fit.

Hard rule:
**Marketing may dramatize wording, not facts.**

## Teaser commitment

Create an `EpisodeCommitment` or equivalent.

Before using a hard CTA such as "Come back tomorrow for the full episode", check:
- the event is teaser-eligible;
- a next-day episode slot exists;
- the Story Engine is enabled;
- no known blocker makes publication impossible.

If certainty is lower, use softer language:
- "This may make tomorrow's episode."
- "The team is already talking about what happened today."

## Marketing campaign object

A Campaign contains:
- campaign_id;
- objective;
- related content/episode/event;
- target audience;
- channel set;
- creative variants;
- CTA;
- schedule;
- budget;
- experiment design;
- safety gates;
- attribution configuration;
- status;
- results.

## Cross-platform adaptation

Do not blindly repost identical copy.

Adapt:
- length;
- aspect ratio;
- caption style;
- hashtags;
- CTA;
- thumbnail/cover;
- timing;
- community tone;
to each platform.

Preserve the same factual source event.

## Community management

Community Manager may:
- publish approved announcements;
- run polls;
- summarize fan sentiment;
- answer low-risk questions;
- route ideas to the Pitch Queue;
- moderate spam/abuse;
- escalate sensitive issues;
- manage Telegram community flows.

Auto-replies must be configurable:
- OFF
- DRAFT_ONLY
- LOW_RISK_AUTONOMOUS
- FULLY_AUTONOMOUS_WITHIN_POLICY

Never expose:
- secrets;
- private Owner instructions;
- security details;
- unpublished sensitive incidents;
- raw system prompts;
- hidden operational data.

## Telegram

Telegram should support, when properly configured:
- channel announcements;
- episode alerts;
- polls;
- teaser drops;
- links;
- fan feedback;
- limited bot interaction;
- future paid-pitch routing.

A Telegram integration requires valid bot/channel permissions. No fake posting.

## Marketing learning

Marketing Analytics should store per post/campaign where available:
- impressions;
- views;
- watch time;
- retention;
- likes;
- comments;
- shares;
- saves;
- follower/subscriber change;
- link clicks;
- episode conversions;
- timestamp;
- platform;
- hook type;
- CTA;
- asset version.

Attribution confidence:
- DIRECT
- PLATFORM_REPORTED
- INFERRED
- CORRELATED
- UNAVAILABLE

Never present inferred attribution as exact causation.

## Experimentation

Examples:
- mystery hook vs conflict hook;
- question vs statement;
- 7-second teaser vs 12-second teaser;
- publish time;
- CTA wording;
- platform-specific creative;
- post before/after a milestone.

Use minimum sample sizes and avoid strategy thrashing from one viral post.

## Crisis/reputation path

If marketing detects:
- sudden negative sentiment;
- rights complaint;
- factual complaint;
- platform warning;
- impersonation/scam;
- security-related public discussion;

then:
- freeze unsafe automated replies if necessary;
- create incident;
- notify CMO/CEO;
- route to Legal/Compliance and Security;
- use approved crisis communication workflow.

## UI

Marketing Department should eventually have a visible office zone/room.

Real backend states can map to:
- writing teaser;
- scheduling campaign;
- monitoring comments;
- reviewing analytics;
- meeting with CEO;
- escalating to Legal.

Again: UI only visualizes real marketing tasks.


# V5 Marketing monetization integration

Marketing may promote monetization mechanisms such as paid pitches, donations, memberships or sponsor offers only when:
- the mechanism is enabled by Owner;
- Legal has approved terms/disclosures;
- Finance has defined revenue classification;
- Community moderation exists;
- no payment guarantees editorial acceptance unless explicitly promised.

Settled audience payments flow through RevenueEvidence → VR$ ledger and may become story/world budget.

# Cross-Platform Social Publishing

## Purpose

Provide one normalized social publishing layer while respecting each platform's real API and policy differences.

## Supported target categories

- YouTube
- TikTok
- Instagram
- Facebook
- Telegram

## Adapter contract

A social adapter may expose only supported capabilities:

- health_check()
- get_account()
- get_capabilities()
- publish_text()
- publish_image()
- publish_video()
- schedule_post()
- delete_post() if supported
- get_post_status()
- get_post_metrics()
- get_comments() if supported
- reply_comment() if supported
- create_poll() if supported
- upload_media()
- refresh_auth()

Capability discovery must be truthful.

## Account states

NOT_CONFIGURED
AUTH_REQUIRED
CONNECTED
DEGRADED
RATE_LIMITED
PERMISSION_MISSING
OFFLINE

## Publishing transaction

Draft
→ policy/rights/marketing gate
→ adapter capability check
→ credential check
→ idempotency key
→ external publish
→ receipt verification
→ Publication record
→ event.

Ambiguous external result:
route to reconciliation/manual repair before retrying blindly.

## Content variants

A `SocialPostGroup` represents one marketing idea.

Each platform gets a `SocialPostVariant`.

Shared:
- source event/content;
- campaign;
- factual grounding.

Platform-specific:
- copy;
- aspect;
- asset;
- hashtags;
- CTA;
- schedule.

## Link tracking

Where practical:
- UTM;
- short links;
- campaign IDs;
- landing-page attribution.

Do not claim exact cross-platform attribution when privacy/platform limits prevent it.

## Rate/spam controls

Prevent:
- duplicate accidental posts;
- high-frequency spam;
- repeated identical caption;
- unbounded automated replies.

## Authentication realism

Some platforms may require:
- business/creator account;
- app review;
- permissions;
- OAuth;
- manually approved scopes.

Expose these as real setup requirements rather than bypassing them.

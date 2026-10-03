from datetime import datetime
from ipaddress import ip_address
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


def validate_public_host(host: str, where: str = "the allowlist") -> str:
    """A bare lowercase public DNS hostname, or a ValueError saying what is wrong with it."""
    if (
        not host
        or host != host.lower()
        or len(host) > 253
        or any(c in host for c in "/:*@ \\?#")
        or host.startswith(".")
        or host.endswith(".")
    ):
        raise ValueError(
            f"Use bare lowercase hostnames in {where}, for example www.iana.org — no scheme, "
            "port, path or wildcard"
        )
    # Naming this machine or a private range here would turn a research allowlist into a
    # way to read internal services, so the studio refuses such an entry outright.
    if host in ("localhost", "localhost.localdomain") or host.endswith(".localhost"):
        raise ValueError(f"{where} names public sources, not this machine")
    try:
        address = ip_address(host)
    except ValueError:
        return host
    if not address.is_global:
        raise ValueError(f"{where} names public sources, not internal addresses")
    return host


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="STUDIO_", env_file=ROOT / ".env", extra="ignore", hide_input_in_errors=True
    )

    owner_token: SecretStr
    name: str = Field(default="AMN-AI", min_length=1, max_length=100)
    timezone: str = "Europe/Bucharest"
    database_url: str = "sqlite:///data/studio.db"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1024, le=65535)
    sheet_blocker_scan_seconds: int = Field(default=300, ge=30, le=86400)
    allowed_hosts: list[str] = ["localhost", "127.0.0.1"]
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # The log file (REL-05): JSON lines in <log_dir>/studio.log, rotated at
    # log_file_max_bytes with log_file_backups older files kept. With no STUDIO_LOG_DIR the
    # folder is `logs` beside the database file (data/logs for the studio's own); an
    # in-memory database, or STUDIO_LOG_TO_FILE=false, logs to the console only.
    log_to_file: bool = True
    log_dir: Path | None = None
    log_file_max_bytes: int = Field(default=10 * 1024 * 1024, ge=64 * 1024, le=1024**3)
    log_file_backups: int = Field(default=10, ge=1, le=100)
    # The console's own level: the Windows service writes the console to a file of its own
    # (scripts/install_studio_service.ps1 sets WARNING), so the rotating file is the full log.
    log_console_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] | None = None

    # Official YouTube Data API v3 credentials. Absent by default: the application must
    # never simulate a publishing integration when these are missing (AGENTS.md).
    youtube_client_id: str | None = None
    youtube_client_secret: SecretStr | None = None
    youtube_refresh_token: SecretStr | None = None
    youtube_channel_id: str | None = None

    # Hosts the research retriever may fetch from, e.g.
    # STUDIO_RESEARCH_ALLOWED_HOSTS=["www.iana.org","www.nasa.gov"]
    #
    # Empty by default. This list is one half of the studio's SSRF boundary; the other half
    # is the table of hosts the Owner adds and tests from the interface
    # (`research_allowed_host`, Owner-authenticated endpoints only). No agent has a tool that
    # reaches either: an allowlist an agent could add to would not be an allowlist.
    research_allowed_hosts: list[str] = []

    # Absolute path to an ffmpeg executable. When unset, PATH is searched.
    ffmpeg_path: str | None = None
    #: Absolute path to ffprobe (STUDIO_FFPROBE_PATH). When unset: PATH, then beside ffmpeg.
    #: Until 2026-10-02 it was read only from the process environment, while the preflight
    #: sent the Owner to .env to set it (REL-13).
    ffprobe_path: str | None = None

    # ----------------------------------------------------- the disk, the media, the backups
    #: Where the films, takes and stills are written (STUDIO_MEDIA_ROOT). Unset: the
    #: studio's own backend/storage/media, as before. A relative path is read from the
    #: studio's folder. Measured 2026-10-01: 299 GiB there, so a buyer puts it on a big disk.
    media_root: Path | None = None
    #: A paid step, and the day's preflight, refuse to start with less free space than this
    #: on the media disk (STUDIO_MIN_FREE_GB; 0 turns the guard off). A film writes up to
    #: about 1.1 GB while it is made, and a disk that fills mid-film loses paid work.
    min_free_gb: float = Field(default=20.0, ge=0.0, le=100_000.0)
    #: The watchdog deletes the shot and card intermediates of FAILED renders older than
    #: `failed_intermediates_days` (STUDIO_SWEEP_FAILED_INTERMEDIATES). Off by default: the
    #: Owner turns it on. Never a take, a still, a film or its sound.
    sweep_failed_intermediates: bool = False
    failed_intermediates_days: int = Field(default=7, ge=1, le=365)
    #: Where the database backups go (STUDIO_BACKUP_DIR). Unset: ``backups`` beside the
    #: database file (data/backups for the studio). Kept: the newest of each of the last
    #: `backup_keep_daily` days and of the `backup_keep_weekly` weeks before them.
    backup_dir: Path | None = None
    backup_keep_daily: int = Field(default=14, ge=1, le=365)
    backup_keep_weekly: int = Field(default=4, ge=0, le=104)
    #: The daily backup's hour on the studio's clock, and the age past which /health/ready
    #: and the page say the backup is stale.
    backup_hour_local: str = Field(default="03:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    backup_max_age_hours: int = Field(default=36, ge=1, le=24 * 30)
    #: After a good backup: completed housekeeping tasks older than this many days, and
    #: outbox rows already sent older than `prune_outbox_days`, are deleted. Events never.
    prune_task_days: int = Field(default=30, ge=1, le=3650)
    prune_outbox_days: int = Field(default=7, ge=1, le=3650)

    # Google's public "trending now" feed for this country code, read once a day and kept as
    # a signal for the Researcher's proposals and the Director's weekly review. A trend is a
    # hook, never a source. STUDIO_TRENDS_GEO=RO; STUDIO_TRENDS_ENABLED=false turns it off.
    trends_enabled: bool = True
    trends_geo: str = Field(default="RO", min_length=2, max_length=8, pattern="^[A-Za-z-]+$")

    # The language the audience reads and hears: narration, titles, descriptions, tags. The
    # Owner's rule is English regardless of the language the office works in; a publication
    # whose metadata is not in this language holds. STUDIO_CONTENT_LANGUAGE=en.
    content_language: str = Field(default="en", min_length=2, max_length=5, pattern="^[a-z-]+$")

    #: Every published description ends with the studio's AI disclosure and a pointer to the
    #: channel that made the film. Both halves are configuration, never code: the site the
    #: disclosure links to (STUDIO_AI_DISCLOSURE_URL, empty until the Owner publishes it) and
    #: the title of the connected YouTube channel credited as the creator
    #: (STUDIO_CREATOR_CHANNEL_TITLE). The link to that channel is read from its stored
    #: connection.
    ai_disclosure_url: str | None = None
    creator_channel_title: str | None = None
    #: The disclosure itself is configuration too (audit PUB-07, 2026-10-02): the studio's
    #: name as the audience reads it (STUDIO_DISPLAY_NAME, named in the disclosure when set),
    #: and the Owner's own sentence per content language (STUDIO_AI_DISCLOSURE_TEXTS, a JSON
    #: object such as {"de": "Hinweis: mit generativer KI erstellt von {studio}."}). Unset,
    #: the studio's built-in English (or Romanian) sentence is used, naming no studio.
    #: Read from STUDIO_DISPLAY_NAME, as documented: with the STUDIO_ prefix the field's own
    #: name would have made it STUDIO_STUDIO_DISPLAY_NAME, which no buyer would ever set (found
    #: by tests/test_env_example.py, 2026-10-02).
    studio_display_name: str | None = Field(
        default=None,
        max_length=80,
        validation_alias=AliasChoices("STUDIO_DISPLAY_NAME", "studio_display_name"),
    )
    ai_disclosure_texts: dict[str, str] = Field(default_factory=dict)
    #: How long a publication may stay STARTED before the watchdog asks YouTube whether the
    #: upload landed (STUDIO_PUBLISH_STUCK_AFTER_SECONDS; read by the watchdog).
    publish_stuck_after_seconds: int = Field(default=3600, ge=300, le=86400)
    #: Whether editorial QC refuses a film (STUDIO_EDITORIAL_QC_BLOCKING). Unset, the look
    #: file's finish decides (config/factual_look.json), which is advisory by default.
    editorial_qc_blocking: bool | None = None

    #: The office scene draws the live weather where the studio is. The service that reports
    #: it is configuration (STUDIO_OFFICE_WEATHER_HOST, an Open-Meteo compatible forecast host);
    #: unset, the scene says the weather is unavailable and draws none. The coordinates are
    #: the office's own (Bucharest by default), also used for sunrise and sunset.
    office_weather_host: str | None = None
    office_latitude: float = Field(default=44.4268, ge=-90, le=90)
    office_longitude: float = Field(default=26.1025, ge=-180, le=180)
    #: The city the page names under its clock and on its title (STUDIO_OFFICE_CITY), and the
    #: country whose public holidays empty the street (STUDIO_HOLIDAY_COUNTRY, ISO 3166 alpha-2;
    #: the page knows only Romania's calendar, so any other country gets ordinary days, and an
    #: empty value none). Served in the snapshot with the timezone and the coordinates
    #: (services.studio_location). The defaults are the first studio's Bucharest; a buyer sets
    #: all four, with STUDIO_TIMEZONE, in .env (SELL-08).
    office_city: str = Field(default="București", min_length=1, max_length=80)
    holiday_country: str = Field(default="RO", pattern=r"^([A-Za-z]{2})?$")
    #: The demo (SELL-03): `scripts/start.py --demo` starts an isolated studio on its own
    #: database and media folder, with every vendor replaced by the local deterministic
    #: adapters and a scripted language model (app.demo). It publishes nothing and buys
    #: nothing: the publishing, payment and connection routes answer 403, and the page shows
    #: a permanent banner. Never set it on a real studio's database.
    demo_mode: bool = False
    #: The headquarters rendered live in Unreal Engine reaches the page over Pixel Streaming. The
    #: page may only talk to its own origin, so the backend relays the stream's signalling to
    #: this address (STUDIO_OFFICE_STREAM_SIGNALLING_URL, the player port of Epic's signalling
    #: server, e.g. ws://127.0.0.1:8890). Unset, the page shows its own renderer.
    office_stream_signalling_url: str | None = None
    #: Where the studio keeps the newest real frame of that stream, for a first visit's title
    #: (backend/app/office/kept_frame.py; STUDIO_OFFICE_KEPT_FRAME_DIR). Unset, an ``office``
    #: folder beside the database file. It holds one small WebP, never the database.
    office_kept_frame_dir: Path | None = None
    #: The same running level answers Unreal's Remote Control HTTP API
    #: (STUDIO_OFFICE_UNREAL_REMOTE_URL, e.g. http://127.0.0.1:30010). Set, the backend shows and
    #: animates the seated employees from the studio's state; the seats are the ones
    #: art-source/unreal/people/seat_employees.py recorded. Unset, the level is left as built.
    office_unreal_remote_url: str | None = None
    office_unreal_seat_report: Path = ROOT / "art-source/unreal/people/seat_report.json"
    office_unreal_sync_seconds: float = Field(default=5.0, ge=1.0, le=300.0)
    #: The real sky over the headquarters (backend/app/office/world.py, scene_params.py). Owner
    #: decision D1, taken as proposed on 2026-09-18: the viewer looks north and the facade faces
    #: south (180), so the evening sun is on the left as in his reference picture, the morning sun
    #: on the right and the noon sun behind the viewer. This one number holds that decision
    #: (STUDIO_OFFICE_FACADE_HEADING_DEG, compass degrees the facade faces).
    office_facade_heading_deg: float = Field(default=180.0, ge=0.0, lt=360.0)
    #: What the rebuild's last step (art-source/unreal/env_report_hq_live.py) writes: the level's
    #: object paths by label, its axes and which emissive components scale uniformly. Until it
    #: exists the environment pass does nothing: an object path is never guessed.
    office_unreal_env_report: Path = ROOT / "art-source/unreal/env_report.json"
    #: The environment pass's cadences (critic's corrected phase 1): everything is sent again
    #: every 20 s (ClockOffsetS with it), a real change of light is eased over 30 s rather than
    #: cut, and the weather is read every 10 min (Open-Meteo refreshes its current block every 15).
    office_unreal_env_refresh_seconds: float = Field(default=20.0, ge=5.0, le=600.0)
    office_unreal_env_ease_seconds: float = Field(default=30.0, ge=0.0, le=600.0)
    office_weather_refresh_seconds: float = Field(default=600.0, ge=60.0, le=3600.0)
    #: A rehearsal hour for the scene (STUDIO_OFFICE_WORLD_REHEARSAL_AT, an aware ISO time), for a
    #: rehearsal on a COPY only: on the Owner's studio (data/studio.db) it is refused and the real
    #: clock is kept (world.world_clock). The weather of a rehearsal is not read.
    office_world_rehearsal_at: datetime | None = None

    #: What the studio optimises for when it picks a model itself. The Owner's standing
    #: instruction is premium: the best picture the account can make, cost secondary — "no
    #: sense having a film company that cannot deliver good films". `balanced` weighs the
    #: four criteria evenly, `thrifty` puts cost first. The weights below are what each
    #: means; every channel may still override them per purpose.
    production_priority: Literal["premium", "balanced", "thrifty"] = "premium"

    #: The most one film may spend on generated motion, in dollars. Measured on the Owner's
    #: account: a six-second shot on `seedance2_5` costs about 2.60 USD, so eight shots are
    #: twenty. A film is worth that; a day of experiments is not, and nothing priced a shot
    #: until the Owner recorded what a credit costs — so the daily budget saw a day that had
    #: spent nothing while twenty-one dollars went out.
    motion_budget_usd: float = 12.0

    #: The most one PRODUCTION film may spend on its paid steps (stills, hero test shot,
    #: motion, paid redos), in dollars (STUDIO_FILM_BUDGET_USD). Before every paid step of the
    #: shooting sheet, what the books already hold for the film plus the step's cap must fit
    #: under it, otherwise the step is refused OVER_FILM_BUDGET (the Owner's explicit consent
    #: on the sheet may go over it). Unset, it is `motion_budget_usd` plus the stills cap of a
    #: six-scene film at the published price (`shooting_sheet.film_ceiling_micros`): 15.24 USD
    #: with the defaults. Measured 2026-10-01: a six-shot seedance2_5 sheet at 1080p caps at
    #: about 26 USD, twice the per-film figure the preflight used to show; the real figure is
    #: the Owner's to set.
    film_budget_usd: float | None = Field(default=None, ge=0.0, le=100_000.0)

    #: How long one film's purchase lease stands before another buyer may take it over
    #: (STUDIO_FILM_PURCHASE_LEASE_SECONDS). A paid step holds the lease while it buys (the page
    #: waits up to 45 minutes for one); a process that died under it leaves the film blocked
    #: only this long. Three hours.
    film_purchase_lease_seconds: int = Field(default=10_800, ge=600, le=86_400)

    #: The resolution the motion step films at (STUDIO_MOTION_RESOLUTION). 1080p is the
    #: delivered frame; 720p is the cheaper alternative the shooting sheet prices beside it.
    motion_resolution: Literal["1080p", "720p"] = "1080p"

    #: How much more than a paid step's next purchase the vendor account must hold before it
    #: is asked or bought (STUDIO_PAID_STEP_BALANCE_MARGIN): its next round to start, each
    #: purchase after it before that purchase (the Owner's rule of 2026-10-03,
    #: `media.balance_rule`); the cap he approved stays the step's ceiling. 1.15: a purchase is
    #: never sent on a balance it could exhaust half-way.
    paid_step_balance_margin: float = Field(default=1.15, ge=1.0, le=3.0)

    #: How many paid attempts a scene may have (its still requests, or its shots) since the
    #: Owner last decided about it on the shooting sheet, whatever its prompt
    #: (STUDIO_MAX_PAID_ATTEMPTS_PER_SCENE). Past it the scene waits for him: a scene that
    #: fails is not bought again every day, and a prompt rewritten every day is not a new
    #: allowance every day. 3 covers one stills request and its two re-rolls, or a shot, its
    #: technical retry and clip QC's retry.
    max_paid_attempts_per_scene: int = Field(default=3, ge=1, le=20)

    #: How many days a factual film may stand still before the Director retires it
    #: (STUDIO_FILM_WAIT_DAYS): held for a fault of its own (a story the gate refused, no shot
    #: plan from the model, a lint BLOCK) or waiting on a refusal (a scene left to the Owner, his
    #: look at the hero, the film's ceiling), with nothing bought and nothing decided since.
    #: The storyboard is then REJECTED with a letter listing what was bought for it, so its
    #: topic stops holding the studio and the next one is chosen (2026-10-02, A4 / AR-02). A
    #: film waiting only for his yes (a question on the sheet) is never retired, only reminded.
    film_wait_days: int = Field(default=3, ge=1, le=60)

    #: The paid scene redos the studio may buy by itself after a film fails quality control
    #: (2026-10-02, A8): per scene (STUDIO_FILM_MAX_PAID_REDOS_PER_SCENE) and per film
    #: (STUDIO_FILM_MAX_PAID_REDOS). A "redo" is one scene's new picture and/or new motion,
    #: each still bought only through `may_act('media.scene_redo')` under his paid-media rule,
    #: the budgets and the film's ceiling: under EVERY_PAID_STEP it is asked, never bought.
    #: The free fixes (the sound remastered, a card recomposed, the film re-encoded from the
    #: same takes) are applied without a limit of their own, once per failed film. 0 turns the
    #: paid redos off. Defaults pending the Owner's decision.
    film_max_paid_redos_per_scene: int = Field(default=1, ge=0, le=5)
    film_max_paid_redos: int = Field(default=2, ge=0, le=20)

    #: How long a short should be. The Owner's answer: about thirty seconds, and the story
    #: decides — twenty-four when that is the film, thirty-four when a premium story needs it.
    #: The writer is briefed with it, and the story review measures the narration against it.
    target_video_seconds: int = 30

    #: How many scenes of a render may be generated as motion. None means every scene; a
    #: small number is what a test render uses, so seeing how a film reads costs one shot
    #: instead of eight. The Owner's instruction: "la teste redam doar minimul".
    motion_scenes_max: int | None = None

    #: How many scenes a TEST render may generate. A test answers "does this work", and two
    #: shots answer it; the Owner's instruction after an afternoon cost twenty-one dollars
    #: was that a test renders the minimum.
    test_motion_scenes: int = 2

    #: What a single TEST generation may cost, and what a TEST second may cost. A request
    #: above either is refused rather than quietly bought: in TEST the studio is checking
    #: that the pipeline works, not what a shot looks like.
    test_max_cost_per_generation_usd: float = 0.60
    test_max_cost_per_second_usd: float = 0.12

    #: Whether the captions are burnt into the picture (STUDIO_CAPTIONS_BURN_IN). On by
    #: default: measured on a rendered 1080x1920 frame, the burnt line sits above the bottom
    #: fifth where the platforms draw their own controls. Off keeps only captions.srt beside
    #: the film, for the platform to carry as a track.
    captions_burn_in: bool = True

    #: How many scenes of a TEST film may be stills pushed slowly before quality control warns
    #: (STUDIO_MAX_FALLBACK_SCENES); None means half the scenes. In TEST two motion scenes are
    #: policy, so the count is only a warning. In PRODUCTION this setting is NOT read: no LIVE
    #: scene may be a still unless the Owner chose "imagine fixă animată local" for that very
    #: scene on the shooting sheet (CLIP_QC, 2026-10-01). The old default of half the scenes
    #: let two of the Nepal film's six scenes through as stills.
    max_fallback_scenes: int | None = Field(default=None, ge=0)

    # ---------------------------------------------------------------- models come and go
    #: Whether a model the vendor has newly exposed is taken into the studio's catalogue at
    #: all. On, because a catalogue the studio refuses to read is a catalogue frozen in the
    #: month someone wrote it down; a new model still starts outside production.
    auto_discover_models: bool = True

    #: Whether the studio may spend money of its own accord to learn what a new model's
    #: picture is like. Off by default: benchmarking is generation, and generation is money.
    auto_benchmark_new_models: bool = False

    #: What the studio may spend on benchmarking in one review, in dollars.
    max_benchmark_budget_usd: float = 1.50

    #: Whether the periodic review may move a model up when its own results justify it, and
    #: down when it keeps failing or costs a multiple of an admitted model for the same job.
    auto_promote_cheaper_better_models: bool = True
    auto_demote_expensive_models: bool = True

    #: How many judged generations a model needs before its results may move it. Below this
    #: a good run is luck, not evidence.
    min_test_samples_for_promotion: int = Field(default=3, ge=1, le=100)

    #: How long a film may hold money it has not spent. The media stage reserves what the
    #: plan is estimated to cost before it generates anything and settles the hold against
    #: the real cost rows when the render is in the books; a hold older than this was left
    #: by a process that died under it, and the watchdog lets it go
    #: (`app.economy.budget.release_stale_reservations`). Six hours: a film takes minutes
    #: and a day of retries hours, so nothing honest is still holding at that age.
    reservation_ttl_seconds: int = Field(default=21600, ge=60, le=86400)

    #: Where a paid render stops being routine spending and becomes the Owner's decision.
    #: `31_GOVERNANCE_APPROVAL_POLICY` puts "paid generation beyond threshold" at T3 and
    #: everything inside the budget at T2, and this is that threshold in dollars: the media
    #: stage asks `app.services.may_act` about `media.paid_generation` for a film estimated
    #: at or under it and about `media.paid_generation_over_threshold` above it, so a
    #: SUPERVISED studio films the ordinary day by itself and asks before the dear film.
    #: Five dollars because a six-second shot on `seedance2_5` costs about 2.60 USD on the
    #: Owner's account: two shots is where one film's spend stops looking like routine.
    #: In AUTONOMOUS_CEO both tiers are allowed, so this line changes nothing until the
    #: Owner lowers the mode — it is the figure his question is asked with, not a budget.
    paid_generation_approval_threshold_usd: float = Field(default=5.0, ge=0.0)

    #: How long one approval request stands, in hours. One number, three consequences, which
    #: is why it belongs here rather than in `app.services` where it was a module constant:
    #: an unanswered question stands this long before it must be asked again; a refusal keeps
    #: the studio from asking about the same thing again for the same span; and a yes cannot
    #: be spent after it — he was asked about today's film, not tomorrow's. A day, so the
    #: Owner's morning is the natural answer; the bounds are an hour (below which a question
    #: could expire before he reads it) and a week.
    approval_expires_after_hours: int = Field(default=24, ge=1, le=168)
    #: How long his question on a paid step of a film stands (the stills, the hero test shot,
    #: the rest of the motion, a one-scene redo, the sheet's narration), in hours
    #: (STUDIO_PAID_MEDIA_APPROVAL_EXPIRES_HOURS). Two days, not one (2026-10-02, AR-05): the
    #: question is raised by the day's media stage, and with 24 h a yes given the next morning
    #: had often expired by the run 24 h later. His yes also continues the film at once
    #: (FILM_CONTINUE), so the hours only matter when the studio cannot.
    paid_media_approval_expires_hours: int = Field(default=48, ge=1, le=168)

    #: The ceiling on what every employee together may spend in tokens in one business date.
    #: 0 means none, which is how the studio has run until now: measured on the live copy,
    #: 391 runs on Ollama Cloud went through the Director's loop and the mail rounds under no
    #: ceiling at all. Past it the Policy Kernel records the run BLOCKED_BUDGET and the
    #: Accountant writes to the Owner once that day (`app.economy.accountant.may_run_agent`);
    #: the letter names this setting as STUDIO_AGENT_DAILY_TOKEN_BUDGET. Independently of it,
    #: an active USD budget that is already EXCEEDED refuses every run the same way
    #: (2026-10-02, MONEY-10), and the preflight degrades when a paid model runs with no
    #: ceiling. The figure is the Owner's; none is chosen for him here.
    agent_daily_token_budget: int = Field(default=0, ge=0)

    #: How much reading the day does: candidates the research stage gathers pages for, and
    #: pages read per candidate. Measured on the live copy: two candidates of three pages
    #: left the studio with nothing on a day when both plans guessed addresses that 404'd.
    #: Clamped to 1..12 by `app.research.service.research_budget`, so a typo in the
    #: environment cannot turn a research pass into a crawl.
    research_candidates_per_day: int = Field(default=4, ge=1, le=12)
    research_pages_per_topic: int = Field(default=4, ge=1, le=12)

    #: A price that moves by at least this much is a letter to the Owner, and a vendor quote
    #: that disagrees with the stored price by more than the tolerance makes it stale.
    price_change_alert_percent: float = Field(default=10.0, ge=0.1, le=1000.0)
    price_stale_tolerance_percent: float = Field(default=5.0, ge=0.1, le=1000.0)

    #: Model names the Owner refuses, as comma-separated shell patterns (`*` matches). The
    #: one thing about models that belongs in configuration: a judgement, not a fact.
    model_deny_list: str = ""

    # The background worker is what makes the studio run without the browser: it fires due
    # scheduled jobs and executes the tasks they enqueue. Off in tests, where a loop that starts
    # the day on its own would make every other test's timing a coincidence.
    worker_enabled: bool = True
    worker_interval_seconds: int = Field(default=30, ge=5, le=3600)

    # ------------------------------------------------------------- the day and the clock
    #: When the day starts, on the studio's own wall clock (HH:MM in `timezone`). The daily
    #: job used to be anchored to the moment the Owner activated it, so a studio started at
    #: 16:40 ran its day at 16:40 for ever after; a fixed local hour is what a schedule is.
    #: The job is still seeded dormant — starting its clock stays the Owner's recorded act.
    daily_run_hour_local: str = Field(default="05:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")

    #: A day that could not run — a BLOCKED preflight, a stage that failed on a transient
    #: fault — is attempted again after this long, up to this many attempts per business
    #: date. Measured on the live copy: one "database is locked" at the wrong second lost
    #: the whole day, because the clock refused a date that had any run at all.
    daily_max_attempts: int = Field(default=3, ge=1, le=10)
    daily_retry_seconds: int = Field(default=1800, ge=30, le=43200)

    #: A stage whose fault is transient — a timeout, a provider's 429 or 5xx, SQLite's
    #: "database is locked" — is retried in place this many times after its first failure,
    #: sleeping `backoff * 2**n` seconds between tries (20, 40, 80). A hard fault (a wrong
    #: value, a policy refusal, a bug) is not retried at all: no amount of waiting fixes it.
    stage_retry_attempts: int = Field(default=3, ge=0, le=10)
    stage_retry_backoff_seconds: int = Field(default=20, ge=0, le=3600)

    #: A vendor's 429 or 5xx, or a connection that never opened, is asked again this many
    #: times, waiting 1, 2, 4… seconds (jittered) up to the cap; a Retry-After the vendor
    #: sends replaces the wait when it fits under the cap, and one above it is raised at once
    #: as the refusal it is — the worker's lease is an hour, and a ten-minute wait inside one
    #: scene would spend it. A billed request that left this machine and got no answer is
    #: never sent again, whatever these say. Measured 2026-09-17: one 503 per scene was a
    #: failed day.
    provider_retry_attempts: int = Field(default=3, ge=1, le=10)
    provider_retry_max_seconds: int = Field(default=30, ge=0, le=600)

    #: How often the watchdog looks for work that is stuck — a task past its lease, a run
    #: that never finished, a provider job never collected. Behind the autonomy stop like
    #: every other scheduled thing.
    watchdog_interval_seconds: int = Field(default=600, ge=60, le=86400)

    #: What the watchdog treats as stuck, and how long it keeps asking. A render RENDERING
    #: longer than this with no end recorded is failed the way the assembler fails one
    #: (measured on the live copy: two rows RENDERING since 2026-09-12, left by a process
    #: that died under them). A platform that cannot be asked about a publication is asked
    #: this many times, then the row is handed to the Owner as NEEDS_RECONCILIATION and not
    #: asked again — every ten minutes for ever is how a studio spends its quota on a dead
    #: endpoint.
    render_stuck_after_seconds: int = Field(default=10800, ge=60, le=86400)
    reconcile_max_attempts: int = Field(default=3, ge=1, le=20)
    provider_catalog_refresh_enabled: bool = True
    provider_catalog_refresh_seconds: int = Field(default=21600, ge=60, le=604800)
    provider_catalog_retry_seconds: int = Field(default=900, ge=30, le=86400)
    provider_catalog_poll_seconds: int = Field(default=60, ge=5, le=3600)

    @property
    def youtube_credentials_present(self) -> bool:
        """True only when a real OAuth credential triple is configured."""
        return bool(
            self.youtube_client_id and self.youtube_client_secret and self.youtube_refresh_token
        )

    @field_validator("owner_token")
    @classmethod
    def strong_token(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("Run scripts/bootstrap.py to configure a unique Owner token")
        return value

    @field_validator("research_allowed_hosts")
    @classmethod
    def plain_hostnames(cls, value: list[str]) -> list[str]:
        """Reject anything that is not a bare lowercase public DNS hostname.

        A scheme, a port, a path or a wildcard here would silently widen the boundary; the
        retriever compares the parsed hostname against these entries exactly. The same rule
        guards the hosts the Owner adds from the interface (`validate_public_host`).
        """
        for host in value:
            validate_public_host(host, "STUDIO_RESEARCH_ALLOWED_HOSTS")
        return value

    @field_validator("media_root", "backup_dir", mode="before")
    @classmethod
    def studio_relative(cls, value: object) -> Path | None:
        """An empty value is unset (``STUDIO_MEDIA_ROOT=`` in .env). A relative folder is the
        studio's own (beside backend/ and data/), not wherever the process was started."""
        if value is None or not str(value).strip():
            return None
        path = Path(str(value).strip())
        return path if path.is_absolute() else ROOT / path

    @field_validator("office_city")
    @classmethod
    def city_words(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("STUDIO_OFFICE_CITY names the city the studio stands in")
        return value

    @field_validator("holiday_country")
    @classmethod
    def country_code(cls, value: str) -> str:
        return value.upper()

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Use an IANA timezone") from exc
        return value

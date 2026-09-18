"""Fields shown only for the chosen service. No example accounts or model names."""


def field(
    key: str,
    label: str,
    required: bool = True,
    secret: bool = False,
    kind: str = "text",
    choices: list[str] | None = None,
) -> dict:
    return dict(
        key=key, label=label, required=required, secret=secret, kind=kind, choices=choices or []
    )


KEY = field("api_key", "Cheie API", secret=True)
MODEL = field("model", "Identificator model")
CLIENT = field("client_id", "Client ID / App ID")
SECRET = field("client_secret", "Client secret / App secret", secret=True)
ACCESS = field("access_token", "Access token", secret=True)
REFRESH = field("refresh_token", "Refresh token", secret=True)
EXPIRY = field("expires_at", "Expiră la (opțional)", False, kind="datetime-local")
REDIRECT = field(
    "redirect_uri", "Redirect URI din aplicația developer (opțional)", False, kind="url"
)
#: What one of the vendor's credits costs the Owner. A vendor that bills in credits states
#: the credits a task will cost and nothing about money; the exchange is the Owner's own
#: purchase, so only the Owner can record it — and until they do, a film's cost is reported
#: in credits rather than guessed in dollars.
CREDIT_USD = field(
    "credit_usd", "Preț pentru un credit, în USD (ex. 0.01 pentru 100 credite = 1 $)", False
)


def service(
    label: str,
    group: str,
    fields: list[dict],
    runtime: str,
    help_text: str,
    docs: str,
    purposes: list[str] | None = None,
) -> dict:
    return dict(
        label=label,
        group=group,
        fields=fields,
        runtime=runtime,
        help=help_text,
        docs=docs,
        purposes=purposes or [],
    )


CATALOG = {
    "ollama": service(
        "Ollama",
        "llm",
        [
            field("base_url", "Adresă server", kind="url"),
            field("api_key", "Cheie API (doar dacă serverul o cere)", False, True),
        ],
        "llm",
        "Modelele se încarcă de pe server după verificare.",
        "https://docs.ollama.com/api",
    ),
    "openai": service(
        "OpenAI",
        "llm",
        [KEY],
        "llm",
        "Cheia API aparține platformei developer; abonamentul ChatGPT nu este o cheie API.",
        "https://platform.openai.com/api-keys",
    ),
    "compatible": service(
        "API compatibil OpenAI",
        "llm",
        [field("base_url", "Adresă API (inclusiv /v1)", kind="url"), KEY],
        "llm",
        "Necesită /models și /chat/completions. Folosește adresa furnizorului ales.",
        "https://developers.openai.com/api/reference/resources/chat",
    ),
    "anthropic": service(
        "Anthropic",
        "llm",
        [KEY],
        "llm",
        "Modelele sunt citite din cont; nu sunt adăugate modele demonstrative.",
        "https://console.anthropic.com/settings/keys",
    ),
    "tiktok": service(
        "TikTok",
        "social",
        [
            field("client_id", "Client key"),
            SECRET,
            ACCESS,
            REFRESH,
            field("account_id", "Open ID utilizator"),
            EXPIRY,
            REDIRECT,
        ],
        "stored",
        "Token de utilizator, cu video.publish pentru publicare. Publicarea TikTok "
        "nu este încă integrată.",
        "https://developers.tiktok.com/doc/content-posting-api-get-started",
    ),
    "instagram": service(
        "Instagram",
        "social",
        [
            CLIENT,
            SECRET,
            ACCESS,
            field("account_id", "ID cont profesional Instagram"),
            EXPIRY,
            REDIRECT,
        ],
        "stored",
        "Instagram Login pentru cont Business/Creator, cu "
        "instagram_business_content_publish. Publicarea nu este încă integrată.",
        " "
        "https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login",
    ),
    "facebook": service(
        "Facebook Page",
        "social",
        [
            CLIENT,
            SECRET,
            field("access_token", "Page access token", secret=True),
            field("account_id", "ID pagină Facebook"),
            EXPIRY,
            REDIRECT,
        ],
        "stored",
        "Token de pagină cu pages_manage_posts. Profilurile personale nu sunt "
        "canale de publicare. Adaptorul de publicare este în așteptare.",
        "https://developers.facebook.com/docs/pages-api/",
    ),
    "elevenlabs": service(
        "ElevenLabs",
        "media",
        [KEY],
        "media",
        "Salvarea verifică cheia și încarcă modelele și vocile din cont. "
        "Modelul și vocea se aleg separat, în configurația de producție.",
        "https://elevenlabs.io/docs/api-reference/introduction",
        ["voice"],
    ),
    "openai_media": service(
        "OpenAI media",
        "media",
        [KEY, MODEL, field("voice_id", "Voce (pentru TTS)", False)],
        "media",
        "Adaugă separat configurațiile pentru imagine, video sau voce. După verificare și "
        "selectare pentru Imagini, randările folosesc imagini reale în loc de substitute.",
        "https://developers.openai.com/api/docs/guides/tools-image-generation",
        ["image", "video", "voice"],
    ),
    "runway": service(
        "Runway",
        "media",
        [KEY, CREDIT_USD],
        "media",
        "Salvarea verifică cheia și încarcă din cont modelele video și de imagine disponibile, "
        "cu limitele lor. Modelele implicite se aleg separat, în configurația de producție, și "
        "rămân doar o rezervă: producția poate alege alt model descoperit.",
        "https://docs.dev.runwayml.com/",
        ["video", "image"],
    ),
    "replicate": service(
        "Replicate",
        "media",
        [KEY, MODEL],
        "stored",
        "Model în formatul furnizorului. Generarea nu este încă conectată în pipeline.",
        "https://replicate.com/docs",
        ["image", "video", "voice", "music"],
    ),
    "email": service(
        "E-mail SMTP / IMAP",
        "social",
        [
            field("address", "Adresă e-mail", kind="email"),
            field("username", "Utilizator"),
            field("password", "Parolă de aplicație", secret=True),
            field("smtp_host", "Server SMTP"),
            field("smtp_port", "Port SMTP", kind="number"),
            field("smtp_security", "Securitate SMTP", choices=["STARTTLS", "TLS"]),
            field("imap_host", "Server IMAP (opțional)", False),
            field("imap_port", "Port IMAP TLS (opțional)", False, kind="number"),
        ],
        "stored",
        "Folosește o parolă de aplicație dacă furnizorul o cere. Accesul IMAP este "
        "opțional. Salvarea nu trimite și nu citește mesaje.",
        "https://support.google.com/accounts/answer/185833",
    ),
    # A web search API the studio may ask for page addresses. Not a source: every address it
    # names is kept only if its host is on the Owner's allowlist and is then read by the
    # studio's own retriever. The fields describe one HTTPS JSON contract, so any engine that
    # answers a GET with a key in a header and a list of {url, title} can be connected.
    "search": service(
        "Căutare web (API JSON)",
        "social",
        [
            field("endpoint", "Adresă API de căutare (HTTPS, fără parametri)", kind="url"),
            field(
                "auth_header",
                "Antetul care poartă cheia (ex. X-Subscription-Token; Authorization trimite "
                "Bearer)",
            ),
            field("results_path", "Calea listei de rezultate în răspuns (ex. web.results)"),
            field("query_param", "Parametrul de interogare (implicit q)", False),
            field("url_field", "Câmpul cu adresa paginii (implicit url)", False),
            field("title_field", "Câmpul cu titlul (implicit title)", False),
            KEY,
        ],
        "search",
        "Motorul întoarce doar adrese. Studioul păstrează numai paginile de pe site-urile "
        "autorizate și le citește el însuși; copia motorului nu este folosită niciodată.",
        "https://github.com/dewitt/opensearch/blob/master/opensearch-1-1-draft-6.md",
    ),
}


#: Prices a public price list documents, seeded as provenance DOCUMENTED and nothing more
#: (`app.economy.prices.seed_documented_prices`). Only where the vendor publishes one figure
#: for every model of the kind and the alternative is narration read as free. Ollama Cloud
#: is deliberately absent: its price is the Owner's plan, and a guess in the books is worse
#: than a gap the Accountant reports. Replaced by the Owner's own price the moment he types it.
DOCUMENTED_PRICES: list[dict[str, str]] = [
    {
        "provider_kind": "elevenlabs",
        "resource": "*",
        "unit": "per_1k_characters",
        # Creator plan on the public price list: 22 USD a month for 100 000 credits, one
        # credit a character on the multilingual models (Flash and Turbo bill half). The
        # Owner's plan may differ; this is the documented figure, not his invoice.
        "usd": "0.22",
        "notes": (
            "DOCUMENTED, not the Owner's plan: ElevenLabs public price list, Creator plan, "
            "22 USD for 100 000 credits a month, one credit per character (Flash/Turbo: half). "
            "Replace with the plan's own price in PUT /economy/prices."
        ),
    },
]

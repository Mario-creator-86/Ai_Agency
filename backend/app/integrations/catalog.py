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
        [KEY, MODEL, field("voice_id", "Voice ID")],
        "media",
        "După verificare și selectare pentru Voce / TTS, narațiunea randărilor este "
        "sintetizată de ElevenLabs.",
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
        [KEY, MODEL],
        "stored",
        "Selectarea salvează preferința. Adaptorul de generare video urmează să fie conectat.",
        "https://docs.dev.runwayml.com/",
        ["video"],
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
}

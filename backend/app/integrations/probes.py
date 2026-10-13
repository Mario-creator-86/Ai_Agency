"""Explicit credential checks; never publishes, generates media or reads mailbox messages."""

import http.client
import imaplib
import json
import smtplib
import ssl
from urllib.parse import quote


def get_json(host: str, path: str, headers: dict) -> dict:
    connection = http.client.HTTPSConnection(host, timeout=8)
    try:
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("Credential verification failed")
        body = response.read(1_000_001)
        if len(body) > 1_000_000:
            raise ValueError("Verification response too large")
        return json.loads(body)
    finally:
        connection.close()


def probe(kind: str, config: dict, secrets: dict) -> bool:
    headers = {"Authorization": "Bearer " + secrets.get("access_token", secrets.get("api_key", ""))}
    if kind == "tiktok":
        data = get_json("open.tiktokapis.com", "/v2/user/info/?fields=open_id", headers)
        return data.get("data", {}).get("user", {}).get("open_id") == config["account_id"]
    if kind == "instagram":
        data = get_json("graph.instagram.com", "/me?fields=user_id,username", headers)
        return str(data.get("user_id")) == config["account_id"]
    if kind == "facebook":
        data = get_json(
            "graph.facebook.com",
            "/" + quote(config["account_id"], safe="") + "?fields=id,name",
            headers,
        )
        return str(data.get("id")) == config["account_id"]
    if kind == "elevenlabs":
        data = get_json("api.elevenlabs.io", "/v1/user", {"xi-api-key": secrets["api_key"]})
        return bool(data.get("user_id"))
    if kind == "replicate":
        data = get_json("api.replicate.com", "/v1/account", headers)
        return bool(data.get("username"))
    if kind == "openai_media":
        data = get_json("api.openai.com", "/v1/models/" + quote(config["model"], safe=""), headers)
        return data.get("id") == config["model"]
    if kind == "search":
        # One query with one neutral word; the answer's shape is what is verified, and
        # nothing it names is stored (app.providers.search.SearchProvider.probe).
        from app.providers.search import SearchProvider, SearchProviderError

        try:
            return SearchProvider(config, secrets["api_key"]).probe()
        except SearchProviderError:
            return False
    if kind == "email":
        context = ssl.create_default_context()
        host, port = config["smtp_host"], int(config["smtp_port"])
        smtp: smtplib.SMTP
        if config["smtp_security"] == "TLS":
            smtp = smtplib.SMTP_SSL(host, port, timeout=8, context=context)
        else:
            smtp = smtplib.SMTP(host, port, timeout=8)
        try:
            smtp.ehlo()
            if config["smtp_security"] == "STARTTLS":
                smtp.starttls(context=context)
                smtp.ehlo()
            smtp.login(config["username"], secrets["password"])
        finally:
            smtp.close()
        if config.get("imap_host"):
            imap = imaplib.IMAP4_SSL(
                config["imap_host"], int(config["imap_port"]), ssl_context=context, timeout=8
            )
            try:
                imap.login(config["username"], secrets["password"])
            finally:
                imap.logout()
        return True
    raise NotImplementedError("Credential verification is not available for this service")

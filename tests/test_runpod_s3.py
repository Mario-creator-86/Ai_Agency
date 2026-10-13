"""The studio's own SigV4 presigner for the Owner's S3-compatible bucket: offline only."""

import asyncio
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest
from app.providers.media_http import MediaProviderError
from pydantic import SecretStr


def s3():
    from app.providers.runpod import s3 as module

    return module


def bucket(**changes):
    from app.providers.runpod.config import BucketConfig

    values = {
        "endpoint_url": "https://account.r2.example",
        "bucket": "amn-films",
        "region": "auto",
        "prefix": "amn/",
        "access_key_id": "AKIDEXAMPLE",
        "secret_access_key": SecretStr("synthetic-secret"),  # pragma: allowlist secret
        "url_ttl_seconds": 604800,
    }
    return BucketConfig(**(values | changes))


def test_aws_published_presigned_get_vector():
    # AWS S3 docs, "Authenticating Requests: Using Query Parameters (SigV4)": the example GET
    # of examplebucket/test.txt on 2013-05-24, 86400 s, us-east-1.
    url = s3().presign_url(
        host="examplebucket.s3.amazonaws.com",
        path="/test.txt",
        method="GET",
        region="us-east-1",
        access_key_id="AKIAIOSFODNN7EXAMPLE",  # pragma: allowlist secret
        secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",  # pragma: allowlist secret
        expires=86400,
        now=datetime(2013, 5, 24, tzinfo=UTC),
    )
    query = parse_qs(urlsplit(url).query)
    # The signature AWS publishes for this example (a public test vector, not a secret).
    published = (
        "aeeed9bbccd4d02ee5c0109b86d86835"  # pragma: allowlist secret
        "f995330da4c265957d157751f604d404"  # pragma: allowlist secret
    )
    assert query["X-Amz-Signature"] == [published]
    scope = "AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request"  # pragma: allowlist secret
    assert query["X-Amz-Credential"] == [scope]


def test_path_style_url_for_any_s3_compatible_endpoint():
    url = s3().presign(
        bucket(), "PUT", "amn/inputs/ab.png", 7200, now=datetime(2026, 10, 8, tzinfo=UTC)
    )
    parts = urlsplit(url)
    assert parts.scheme == "https" and parts.hostname == "account.r2.example"
    assert parts.path == "/amn-films/amn/inputs/ab.png"
    query = parse_qs(parts.query)
    assert query["X-Amz-Expires"] == ["7200"]
    assert query["X-Amz-Credential"][0].endswith("/20261008/auto/s3/aws4_request")
    assert "synthetic-secret" not in url


@pytest.mark.parametrize("expires", [0, 604801])
def test_presign_refuses_out_of_range_lifetimes(expires):
    with pytest.raises(ValueError):
        s3().presign(bucket(), "GET", "amn/x", expires)


@pytest.mark.parametrize("key", ["../x", "", "/abs", "a\nb"])
def test_presign_refuses_unsafe_keys(key):
    with pytest.raises(ValueError):
        s3().presign(bucket(), "GET", key, 60)


class Transport:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, host, method, path, headers, body=None, **kwargs):
        self.calls.append((host, method, path, dict(headers), body, kwargs))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def test_put_bytes_sends_the_object_without_credentials_in_headers():
    transport = Transport([(None, b"", "text/plain")])
    asyncio.run(s3().put_bytes(bucket(), "amn/inputs/x.png", b"\x89PNG", "image/png", transport))
    host, method, path, headers, body, kwargs = transport.calls[0]
    assert host == "account.r2.example" and method == "PUT" and body == b"\x89PNG"
    assert path.startswith("/amn-films/amn/inputs/x.png?")
    assert headers["Content-Type"] == "image/png"
    assert "Authorization" not in headers
    assert kwargs["expect_json"] is False


def test_get_json_reads_a_manifest_and_a_missing_one_is_none():
    transport = Transport(
        [
            ({"status": "COMPLETED"}, b"{}", "application/json"),
            MediaProviderError("nf", http_status=404),
        ]
    )
    assert asyncio.run(s3().get_json(bucket(), "amn/manifests/k.json", transport)) == {
        "status": "COMPLETED"
    }
    assert asyncio.run(s3().get_json(bucket(), "amn/manifests/k.json", transport)) is None


def test_get_json_a_refused_key_is_not_read_as_missing():
    transport = Transport([MediaProviderError("denied", http_status=403)])
    with pytest.raises(MediaProviderError):
        asyncio.run(s3().get_json(bucket(), "amn/manifests/k.json", transport))

"""X-Hub-Signature-256 signing tests."""

import hashlib
import hmac

from wa_agent_test.payloads import (
    SIGNATURE_HEADER,
    BusinessAccount,
    SimulatedUser,
    build_text,
    serialize_payload,
    sign_body,
    verify_signature,
)


def test_header_name() -> None:
    assert SIGNATURE_HEADER == "X-Hub-Signature-256"


def test_known_hmac_sha256_vector() -> None:
    # Standard HMAC-SHA256 test vector (Wikipedia).
    body = b"The quick brown fox jumps over the lazy dog"
    expected = "sha256=f7bc83f430538424b13298e6aa6fb143ef4d59a14946175997479dbc2d1a3cd8"
    assert sign_body(body, "key") == expected


def test_signature_matches_independent_hmac() -> None:
    body = serialize_payload(build_text(BusinessAccount(), SimulatedUser("9", "+9", "n"), "hi"))
    digest = hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert sign_body(body, "s3cret") == f"sha256={digest}"


def test_verify_roundtrip_and_failures() -> None:
    body = b'{"a":1}'
    header = sign_body(body, "secret")
    assert verify_signature(body, header, "secret")
    assert not verify_signature(body, header, "other-secret")
    assert not verify_signature(b'{"a":2}', header, "secret")
    assert not verify_signature(body, None, "secret")
    assert not verify_signature(body, "", "secret")
    assert not verify_signature(body, header.removeprefix("sha256="), "secret")
    assert not verify_signature(body, "sha1=" + header.removeprefix("sha256="), "secret")


def test_serialization_is_compact_and_escapes_non_ascii() -> None:
    body = serialize_payload({"a": "é✓", "b": [1, 2]})
    assert body == b'{"a":"\\u00e9\\u2713","b":[1,2]}'

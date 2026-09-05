"""
Who may start a workflow.

``POST /webhook`` accepted any body from any caller. What a caller could make
the system do with it: spend model credit; post comments on any pull request
the GitHub token could reach; and -- with ``trigger_type: pagerduty`` -- change
the status of a PagerDuty incident, where the tool resolved the incident for
any action other than "acknowledge".

GitHub signs webhook deliveries: ``X-Hub-Signature-256: sha256=<hmac>`` over
the raw body with the shared secret. Verifying it costs one line and is the
difference between "GitHub sent this" and "someone sent this". Manual
triggers, which have no GitHub signature, may present ``X-API-Key`` instead.
"""

from __future__ import annotations

import hashlib
import hmac

from config import settings

SIGNATURE_HEADER = "X-Hub-Signature-256"
API_KEY_HEADER = "X-API-Key"


def sign(body: bytes, secret: str) -> str:
    """The header value GitHub would send for ``body``."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def signature_is_valid(body: bytes, header_value: str | None, secret: str) -> bool:
    if not secret or not header_value:
        return False
    expected = sign(body, secret)
    return hmac.compare_digest(expected, header_value.strip())


def api_key_is_valid(header_value: str | None, expected: str) -> bool:
    if not expected or not header_value:
        return False
    return hmac.compare_digest(expected, header_value.strip())


def is_authorised(body: bytes, signature: str | None, api_key: str | None) -> bool:
    """
    A request is authorised by a valid signature, or by a valid API key.

    With neither secret configured the request is allowed -- development only;
    ``Settings.problems()`` refuses that configuration in production and the
    lifespan check raises on it.
    """
    if not settings.has_webhook_secret and not settings.has_api_key:
        return True
    if settings.has_webhook_secret and signature_is_valid(body, signature, settings.WEBHOOK_SECRET):
        return True
    return settings.has_api_key and api_key_is_valid(api_key, settings.API_KEY)

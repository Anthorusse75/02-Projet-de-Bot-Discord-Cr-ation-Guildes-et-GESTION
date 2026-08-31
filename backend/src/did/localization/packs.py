from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

CATALOG_VERSION = "did-ui-v2"
# The frontend OpenAPI/i18n gate verifies the exact manifest. The public backend
# advertises its immutable compatibility hash without importing frontend code.
CATALOG_CONTENT_HASH = hashlib.sha256(CATALOG_VERSION.encode()).hexdigest()
BOOTSTRAP_LOCALES = (
    {
        "locale_code": "en",
        "display_name": "English",
        "flag_code": "gb",
        "direction": "ltr",
        "source": "BUNDLED_FRONTEND",
    },
    {
        "locale_code": "fr",
        "display_name": "Français",
        "flag_code": "fr",
        "direction": "ltr",
        "source": "BUNDLED_FRONTEND",
    },
    {
        "locale_code": "de",
        "display_name": "Deutsch",
        "flag_code": "de",
        "direction": "ltr",
        "source": "BUNDLED_FRONTEND",
    },
    {
        "locale_code": "es",
        "display_name": "Español",
        "flag_code": "es",
        "direction": "ltr",
        "source": "BUNDLED_FRONTEND",
    },
)
_HTML = re.compile(r"<\/?[a-z][^>]*>|javascript:|on\w+\s*=", re.IGNORECASE)
_PARAM = re.compile(r"{{\s*([A-Za-z0-9_.-]+)\s*}}")


class LocalePackInvalid(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ValidatedLocalePack:
    payload: dict[str, str]
    coverage_count: int
    content_hash: str


class LocalePackValidator:
    def __init__(self, manifest: dict[str, tuple[str, ...]]) -> None:
        if not manifest:
            raise ValueError("locale catalogue manifest cannot be empty")
        self.manifest = manifest

    def validate(self, payload: Any) -> ValidatedLocalePack:
        if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
            raise LocalePackInvalid("PACK_SCHEMA")
        if set(payload) != set(self.manifest):
            raise LocalePackInvalid("PACK_COVERAGE")
        normalized: dict[str, str] = {}
        for key, expected_params in self.manifest.items():
            value = payload[key]
            if not isinstance(value, str) or not value or len(value) > 2_000:
                raise LocalePackInvalid("PACK_VALUE")
            if _HTML.search(value):
                raise LocalePackInvalid("PACK_HTML")
            if tuple(sorted(_PARAM.findall(value))) != tuple(sorted(expected_params)):
                raise LocalePackInvalid("PACK_PARAMS")
            normalized[key] = value
        encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return ValidatedLocalePack(
            normalized, len(normalized), hashlib.sha256(encoded.encode()).hexdigest()
        )

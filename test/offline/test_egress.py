"""Offline tests for the egress whitelist (TP-004, SEC-003, S2 evidence).

Adversarial coverage: unknown hosts, plain HTTP, and IP literals are
refused explicitly; only whitelisted (and dynamically allowed)
HTTPS hosts pass.
"""

import pytest

from stockinsider.shared.egress import (
    EGRESS_WHITELIST,
    EgressViolationError,
    validate_egress_url,
)


def test_whitelisted_vendor_domain_passes() -> None:
    validate_egress_url("https://api.eodhd.com/eod/TSLA.US")
    validate_egress_url("https://api.gdeltproject.org/api/v2/doc/doc")


def test_whitelisted_subdomain_passes() -> None:
    validate_egress_url("https://data.api.eodhd.com/xyz")


def test_unknown_domain_rejected() -> None:
    with pytest.raises(EgressViolationError, match="not in whitelist"):
        validate_egress_url("https://evil.example.com/data")


def test_plain_http_rejected() -> None:
    with pytest.raises(EgressViolationError, match="non-HTTPS"):
        validate_egress_url("http://api.eodhd.com/eod")


def test_ip_literal_rejected() -> None:
    with pytest.raises(EgressViolationError, match="not in whitelist"):
        validate_egress_url("https://93.184.216.34/data")


def test_lookalike_domain_rejected() -> None:
    with pytest.raises(EgressViolationError, match="not in whitelist"):
        validate_egress_url("https://api.eodhd.com.evil.example/x")


def test_extra_allowed_dynamic_endpoint_passes() -> None:
    validate_egress_url("https://api.deepseek.com/v1", extra_allowed=("api.deepseek.com",))


def test_extra_allowed_scoped_to_its_domain() -> None:
    with pytest.raises(EgressViolationError, match="not in whitelist"):
        validate_egress_url("https://evil.example.com/x", extra_allowed=("api.deepseek.com",))


def test_whitelist_contents_are_the_vendor_domains() -> None:
    assert EGRESS_WHITELIST == frozenset({"api.eodhd.com", "api.gdeltproject.org"})

"""Unit tests for the header analysis service."""

import pytest

from app.services.header_analysis import (
    analyze_headers,
    check_display_name_spoofing,
    check_reply_to_mismatch,
    check_return_path_mismatch,
    parse_authentication_results,
)

# ---------------------------------------------------------------------------
# parse_authentication_results
# ---------------------------------------------------------------------------


class TestParseAuthenticationResults:
    def test_all_pass(self):
        headers = {
            "Authentication-Results": (
                "mx.example.com; spf=pass smtp.mailfrom=example.com; "
                "dkim=pass header.d=example.com; dmarc=pass header.from=example.com"
            )
        }
        result = parse_authentication_results(headers)
        assert result["spf"]["result"] == "pass"
        assert result["dkim"]["result"] == "pass"
        assert result["dmarc"]["result"] == "pass"

    def test_mixed_results(self):
        headers = {
            "Authentication-Results": (
                "mx.example.com; spf=fail smtp.mailfrom=evil.com; "
                "dkim=pass header.d=example.com; dmarc=fail header.from=example.com"
            )
        }
        result = parse_authentication_results(headers)
        assert result["spf"]["result"] == "fail"
        assert result["dkim"]["result"] == "pass"
        assert result["dmarc"]["result"] == "fail"

    @pytest.mark.parametrize(
        ("auth_value", "key", "expected_result"),
        [
            ("mx.example.com; spf=softfail smtp.mailfrom=x.com", "spf", "softfail"),
            ("mx.example.com; spf=neutral smtp.mailfrom=x.com", "spf", "neutral"),
            ("mx.example.com; spf=none smtp.mailfrom=x.com", "spf", "none"),
            ("mx.example.com; dkim=temperror header.d=x.com", "dkim", "temperror"),
        ],
        ids=["softfail", "neutral", "none", "temperror"],
    )
    def test_non_pass_statuses(self, auth_value: str, key: str, expected_result: str):
        headers = {"Authentication-Results": auth_value}
        result = parse_authentication_results(headers)
        assert result[key]["result"] == expected_result

    def test_missing_header_returns_empty(self):
        assert parse_authentication_results({}) == {}

    def test_multiple_headers_joined_by_newline(self):
        headers = {
            "Authentication-Results": (
                "mx.example.com; spf=pass smtp.mailfrom=example.com\n"
                "mx.example.com; dkim=pass header.d=example.com; "
                "dmarc=fail header.from=example.com"
            )
        }
        result = parse_authentication_results(headers)
        assert result["spf"]["result"] == "pass"
        assert result["dkim"]["result"] == "pass"
        assert result["dmarc"]["result"] == "fail"

    def test_malformed_header_does_not_raise(self):
        headers = {"Authentication-Results": ";;;garbage===value;;;"}
        result = parse_authentication_results(headers)
        assert isinstance(result, dict)

    def test_arc_header_parsed(self):
        headers = {
            "ARC-Authentication-Results": (
                "i=1; mx.example.com; spf=pass smtp.mailfrom=example.com; "
                "dkim=pass header.d=example.com; dmarc=pass header.from=example.com"
            )
        }
        result = parse_authentication_results(headers)
        assert result["spf"]["result"] == "pass"
        assert result["dkim"]["result"] == "pass"
        assert result["dmarc"]["result"] == "pass"

    def test_first_result_wins_on_duplicate(self):
        headers = {
            "Authentication-Results": (
                "mx.example.com; spf=pass smtp.mailfrom=example.com; spf=fail smtp.mailfrom=evil.com"
            )
        }
        result = parse_authentication_results(headers)
        assert result["spf"]["result"] == "pass"

    def test_detail_extraction(self):
        headers = {"Authentication-Results": "mx.example.com; spf=pass smtp.mailfrom=test@example.com"}
        result = parse_authentication_results(headers)
        assert "smtp.mailfrom=test@example.com" in result["spf"]["detail"]


# ---------------------------------------------------------------------------
# check_reply_to_mismatch
# ---------------------------------------------------------------------------


class TestCheckReplyToMismatch:
    def test_matching_domain_no_mismatch(self):
        headers = {"Reply-To": "support@example.com"}
        is_mismatch, _ = check_reply_to_mismatch(headers, "example.com")
        assert is_mismatch is False

    def test_different_domain_returns_mismatch(self):
        headers = {"Reply-To": "phish@evil.com"}
        is_mismatch, domain = check_reply_to_mismatch(headers, "example.com")
        assert is_mismatch is True
        assert domain == "evil.com"

    def test_missing_reply_to_no_mismatch(self):
        is_mismatch, _ = check_reply_to_mismatch({}, "example.com")
        assert is_mismatch is False


# ---------------------------------------------------------------------------
# check_display_name_spoofing
# ---------------------------------------------------------------------------


class TestCheckDisplayNameSpoofing:
    def test_clean_name_not_spoofed(self):
        is_spoofed, _ = check_display_name_spoofing("John Doe", "john@example.com")
        assert is_spoofed is False

    def test_different_email_in_name_is_spoofed(self):
        is_spoofed, found = check_display_name_spoofing("admin@bank.com", "phisher@evil.com")
        assert is_spoofed is True
        assert found == "admin@bank.com"

    def test_same_email_in_name_not_spoofed(self):
        is_spoofed, _ = check_display_name_spoofing("john@example.com", "john@example.com")
        assert is_spoofed is False

    def test_empty_name_not_spoofed(self):
        is_spoofed, _ = check_display_name_spoofing("", "john@example.com")
        assert is_spoofed is False


# ---------------------------------------------------------------------------
# check_return_path_mismatch
# ---------------------------------------------------------------------------


class TestCheckReturnPathMismatch:
    def test_matching_domain_no_mismatch(self):
        headers = {"Return-Path": "<bounce@example.com>"}
        is_mismatch, _ = check_return_path_mismatch(headers, "example.com")
        assert is_mismatch is False

    def test_different_domain_returns_mismatch(self):
        headers = {"Return-Path": "<bounce@evil.com>"}
        is_mismatch, rp = check_return_path_mismatch(headers, "example.com")
        assert is_mismatch is True
        assert "evil.com" in rp

    def test_missing_return_path_no_mismatch(self):
        is_mismatch, _ = check_return_path_mismatch({}, "example.com")
        assert is_mismatch is False


# ---------------------------------------------------------------------------
# analyze_headers (integration)
# ---------------------------------------------------------------------------


class TestAnalyzeHeaders:
    def test_full_header_set(self):
        headers = {
            "Authentication-Results": (
                "mx.example.com; spf=pass smtp.mailfrom=example.com; "
                "dkim=pass header.d=example.com; dmarc=pass header.from=example.com"
            ),
            "Reply-To": "support@example.com",
            "Return-Path": "<bounce@example.com>",
        }
        result = analyze_headers(headers, "user@example.com", "Example User")
        assert result["from_domain"] == "example.com"
        assert result["spf"]["result"] == "pass"
        assert result["dkim"]["result"] == "pass"
        assert result["dmarc"]["result"] == "pass"
        # No mismatches — these keys should not be present
        assert "reply_to_mismatch" not in result
        assert "return_path_mismatch" not in result

    def test_empty_headers(self):
        result = analyze_headers({}, "user@example.com")
        assert result["from_domain"] == "example.com"
        assert "spf" not in result

    def test_all_mismatches_detected(self):
        headers = {
            "Authentication-Results": "mx.example.com; spf=fail smtp.mailfrom=evil.com; dmarc=fail",
            "Reply-To": "attacker@evil.com",
            "Return-Path": "<bounce@evil.com>",
        }
        result = analyze_headers(headers, "user@example.com", "admin@bank.com")
        assert result["spf"]["result"] == "fail"
        assert result["dmarc"]["result"] == "fail"
        assert result["reply_to_mismatch"] is True
        assert result["return_path_mismatch"] is True
        assert result["display_name_spoofing"] is True

"""Tests for the login rate limiter's atomic INCR+EXPIRE behaviour."""

from __future__ import annotations

from conftest import FakeValkey


async def test_eval_sets_ttl_on_first_call():
    """TTL must always be set when the rate-limit key is first created."""
    fv = FakeValkey()
    result = await fv.eval("", 1, "auth_rate:1.2.3.4", 60)
    assert result == 1
    assert fv._ttls.get("auth_rate:1.2.3.4") == 60


async def test_eval_increments_without_resetting_ttl():
    """Subsequent calls increment but do not reset the TTL."""
    fv = FakeValkey()
    await fv.eval("", 1, "auth_rate:1.2.3.4", 60)
    fv._ttls["auth_rate:1.2.3.4"] = 42  # simulate time passing

    result = await fv.eval("", 1, "auth_rate:1.2.3.4", 60)
    assert result == 2
    # TTL should NOT have been reset (only set when current==1)
    assert fv._ttls["auth_rate:1.2.3.4"] == 42

"""Unit tests for password/user validation and login throttling."""

from __future__ import annotations

import pytest

import config
import security


def test_hash_and_verify_roundtrip():
    hashed = security.hash_password("abcd")
    assert hashed != "abcd"
    assert security.verify_password("abcd", hashed)
    assert not security.verify_password("wrong", hashed)


def test_verify_password_handles_malformed_hash():
    assert security.verify_password("x", "not-a-real-hash") is False


@pytest.mark.parametrize("password", ["", "a", "ab", "abc"])
def test_password_shorter_than_minimum_rejected(password):
    with pytest.raises(security.AuthError):
        security.validate_password(password)


def test_password_at_minimum_length_accepted():
    security.validate_password("a" * config.PASSWORD_MIN_LENGTH)


def test_password_maximum_length_enforced():
    security.validate_password("a" * config.PASSWORD_MAX_LENGTH)
    with pytest.raises(security.AuthError):
        security.validate_password("a" * (config.PASSWORD_MAX_LENGTH + 1))


def test_password_must_be_text():
    with pytest.raises(security.AuthError):
        security.validate_password(None)  # type: ignore[arg-type]


@pytest.mark.parametrize("username", ["abc", "user_name", "a-b.c", "User123"])
def test_valid_usernames(username):
    security.validate_username(username)


@pytest.mark.parametrize("username", ["ab", "", "has space", "bad!", "-leading", "x" * 61])
def test_invalid_usernames(username):
    with pytest.raises(security.AuthError):
        security.validate_username(username)


@pytest.mark.parametrize("email", ["a@b.co", "first.last@example.com", "x+tag@sub.domain.org"])
def test_valid_emails(email):
    security.validate_email(email)


@pytest.mark.parametrize("email", ["", "no-at", "a@b", "a b@c.com", "@b.com", "a@.com"])
def test_invalid_emails(email):
    with pytest.raises(security.AuthError):
        security.validate_email(email)


def test_role_helpers():
    admin = {"role": "Administrator"}
    dev = {"role": "Developer"}
    viewer = {"role": "Viewer"}
    assert security.is_admin(admin) and not security.is_admin(dev)
    assert security.can_write(admin) and security.can_write(dev)
    assert not security.can_write(viewer)
    with pytest.raises(security.Forbidden):
        security.require_write(viewer)
    with pytest.raises(security.Forbidden):
        security.require_admin(dev)


def test_login_throttle_locks_after_max_attempts(monkeypatch):
    throttle = security.LoginThrottle()
    monkeypatch.setattr(config, "LOGIN_MAX_ATTEMPTS", 3)
    assert throttle.is_locked("bob") == 0
    for _ in range(3):
        throttle.register_failure("bob")
    assert throttle.is_locked("bob") > 0


def test_login_throttle_reset_clears_lock():
    throttle = security.LoginThrottle()
    for _ in range(config.LOGIN_MAX_ATTEMPTS):
        throttle.register_failure("bob")
    assert throttle.is_locked("bob") > 0
    throttle.reset("bob")
    assert throttle.is_locked("bob") == 0


def test_login_throttle_is_case_insensitive():
    throttle = security.LoginThrottle()
    for _ in range(config.LOGIN_MAX_ATTEMPTS):
        throttle.register_failure("Bob")
    assert throttle.is_locked("bob") > 0

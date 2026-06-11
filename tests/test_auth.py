"""Basic auth behavior tests for token TTL, models, and page routes."""

import time
import pytest
from fastapi.testclient import TestClient

from main import app
from models.users import UserLogin, TwoFactorLogin
from utils.security import create_access_token, decode_token

client = TestClient(app)


class TestRememberMeTokenTTL:
    def test_access_token_without_remember_me_is_1_day(self):
        token = create_access_token("user-123", remember_me=False)
        payload = decode_token(token, "access")
        ttl_hours = (payload["exp"] - int(time.time())) / 3600
        assert 23.5 < ttl_hours < 24.5

    def test_access_token_with_remember_me_is_30_days(self):
        token = create_access_token("user-123", remember_me=True)
        payload = decode_token(token, "access")
        ttl_days = (payload["exp"] - int(time.time())) / 86400
        assert 29.5 < ttl_days < 30.5


class TestUserLoginModel:
    def test_remember_me_defaults_to_false(self):
        login = UserLogin(email="test@example.com", password="secret")
        assert login.remember_me is False

    def test_remember_me_can_be_true(self):
        login = UserLogin(email="test@example.com", password="secret", remember_me=True)
        assert login.remember_me is True


class TestTwoFactorLoginModel:
    def test_remember_me_defaults_to_false(self):
        tfa = TwoFactorLogin(temp_token="a" * 16, code="123456")
        assert tfa.remember_me is False

    def test_remember_me_can_be_true(self):
        tfa = TwoFactorLogin(temp_token="a" * 16, code="123456", remember_me=True)
        assert tfa.remember_me is True


class TestAuthPageRoutes:
    def test_login_page_returns_200(self):
        response = client.get("/login")
        assert response.status_code == 200
        assert "Remember me" in response.text

    def test_register_page_returns_200(self):
        response = client.get("/register")
        assert response.status_code == 200
        assert "Terms of Use" in response.text
        assert "Privacy Policy" in response.text

    def test_terms_of_use_page_returns_200(self):
        response = client.get("/terms-of-use")
        assert response.status_code == 200
        assert "Terms of Use" in response.text

    def test_privacy_policy_page_returns_200(self):
        response = client.get("/privacy-policy")
        assert response.status_code == 200
        assert "Privacy Policy" in response.text

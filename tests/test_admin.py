"""Admin panel tests for role-based access, dashboards, and management."""

import pytest
from fastapi.testclient import TestClient

from main import app
from database.connection import get_pg_cursor
from utils.security import create_access_token

client = TestClient(app)


def create_user_direct(email, password, full_name, roles):
    from uuid import uuid4
    with get_pg_cursor(commit=True) as cursor:
        cursor.execute("DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE email = %s)", (email,))
        cursor.execute("DELETE FROM users WHERE email = %s", (email,))
        user_id = str(uuid4())
        cursor.execute(
            """
            INSERT INTO users (id, email, password, full_name, status, onboarding_status)
            VALUES (%s, %s, %s, %s, 'ACTIVE', 'COMPLETED')
            RETURNING *
            """,
            (user_id, email, password, full_name),
        )
        user = dict(cursor.fetchone())
        for role in roles:
            cursor.execute(
                "INSERT INTO user_roles (user_id, role) VALUES (%s, %s)",
                (user_id, role),
            )
    return user


def login_token(email, password):
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]


@pytest.fixture
def admin_user():
    user = create_user_direct("admin_test@example.com", "password123", "Admin User", ["ADMIN"])
    token = create_access_token(user["id"])
    return {"user": user, "token": token}


@pytest.fixture
def normal_user():
    user = create_user_direct("normal_test@example.com", "password123", "Normal User", ["APPLICANT"])
    token = create_access_token(user["id"])
    return {"user": user, "token": token}


class TestAdminAccess:
    def test_admin_login_page_returns_200(self):
        response = client.get("/admin/login")
        assert response.status_code == 200
        assert "Admin Paneli" in response.text

    def test_admin_dashboard_page_returns_200(self, admin_user):
        response = client.get("/admin", headers={"Authorization": f"Bearer {admin_user['token']}"})
        assert response.status_code == 200

    def test_normal_user_cannot_access_admin_api(self, normal_user):
        resp = client.get("/api/v1/admin/dashboard/stats", headers={"Authorization": f"Bearer {normal_user['token']}"})
        assert resp.status_code == 403
        assert resp.json()["errors"][0]["code"] == "ADMIN_REQUIRED"

    def test_unauthenticated_user_cannot_access_admin_api(self):
        resp = client.get("/api/v1/admin/dashboard/stats")
        assert resp.status_code == 401

    def test_admin_can_list_users(self, admin_user):
        resp = client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {admin_user['token']}"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["data"], list)
        assert "meta" in data

    def test_admin_can_block_and_unblock_user(self, admin_user, normal_user):
        uid = normal_user["user"]["id"]
        resp = client.patch(
            f"/api/v1/admin/users/{uid}/block",
            json={"is_blocked": True},
            headers={"Authorization": f"Bearer {admin_user['token']}"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["is_blocked"] is True

        resp = client.patch(
            f"/api/v1/admin/users/{uid}/block",
            json={"is_blocked": False},
            headers={"Authorization": f"Bearer {admin_user['token']}"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["is_blocked"] is False

    def test_admin_can_update_user_role(self, admin_user, normal_user):
        uid = normal_user["user"]["id"]
        resp = client.patch(
            f"/api/v1/admin/users/{uid}/role",
            json={"role": "ADMIN", "action": "add"},
            headers={"Authorization": f"Bearer {admin_user['token']}"},
        )
        assert resp.status_code == 200
        assert "ADMIN" in resp.json()["data"]["roles"]

        # cleanup: remove admin role
        client.patch(
            f"/api/v1/admin/users/{uid}/role",
            json={"role": "ADMIN", "action": "remove"},
            headers={"Authorization": f"Bearer {admin_user['token']}"},
        )

    def test_admin_dashboard_stats_correct(self, admin_user):
        resp = client.get("/api/v1/admin/dashboard/stats", headers={"Authorization": f"Bearer {admin_user['token']}"})
        assert resp.status_code == 200
        stats = resp.json()["data"]
        assert isinstance(stats["total_users"], int)
        assert isinstance(stats["total_jobs"], int)

    def test_admin_can_access_settings(self, admin_user):
        resp = client.get("/api/v1/admin/settings", headers={"Authorization": f"Bearer {admin_user['token']}"})
        assert resp.status_code == 200
        settings = resp.json()["data"]
        assert "site_name" in settings

    def test_admin_can_update_settings(self, admin_user):
        resp = client.put(
            "/api/v1/admin/settings",
            json={"site_name": "TestBoard", "contact_email": "test@board.com"},
            headers={"Authorization": f"Bearer {admin_user['token']}"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["site_name"] == "TestBoard"

    def test_admin_logs_list(self, admin_user):
        resp = client.get("/api/v1/admin/logs", headers={"Authorization": f"Bearer {admin_user['token']}"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["data"], list)

    def test_admin_can_delete_user(self, admin_user):
        user = create_user_direct("disposable@example.com", "password123", "Disposable", ["APPLICANT"])
        resp = client.delete(
            f"/api/v1/admin/users/{user['id']}",
            headers={"Authorization": f"Bearer {admin_user['token']}"},
        )
        assert resp.status_code == 200

    def test_admin_cannot_delete_self(self, admin_user):
        resp = client.delete(
            f"/api/v1/admin/users/{admin_user['user']['id']}",
            headers={"Authorization": f"Bearer {admin_user['token']}"},
        )
        assert resp.status_code == 403

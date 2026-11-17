"""隔离入口必须显式开启且经过内部鉴权。"""

import pytest
from fastapi.testclient import TestClient

from pet_common.config import get_settings
from web_api.routers.social_test import store
from web_api.social_test_app import app


def test_gate_auth_and_consent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOCIAL_TEST_ENABLED", "true")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "social-test-secret")
    get_settings.cache_clear()
    store.rooms.clear()
    client = TestClient(app)
    path = "/api/internal/social/test-rooms"
    body = {"device_uid": "d8:85:ac:bb:b0:80", "consented": True}
    headers = {"X-Internal-Token": "social-test-secret"}
    try:
        assert client.post(path, json=body).status_code == 401
        refused = client.post(path, json={**body, "consented": False}, headers=headers)
        assert refused.status_code == 422
        response = client.post(path, json=body, headers=headers)
        assert response.status_code == 200
        assert response.json()["peer_identity"]["mbti"] == "INFP"
        monkeypatch.setenv("SOCIAL_TEST_ENABLED", "false")
        get_settings.cache_clear()
        assert client.post(path, json=body, headers=headers).status_code == 404
    finally:
        get_settings.cache_clear()
        store.rooms.clear()

"""陪伴约定与候选偏好的边界回归。"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from pet_common.companion import CompanionFollowup
from pet_common.models import Device, Memory
from web_api.routers.companion import (
    FollowupIn,
    FollowupUpdate,
    allowed_followup_time,
    approved_preferences,
    create_followup,
    device_scope,
    preference_tag,
    update_for_device,
)


def test_candidate_never_affects_strategy() -> None:
    candidate = Memory(status="candidate", tags=["preference:tone:direct"])
    active = Memory(status="active", tags=["preference:tone:gentle"])
    assert approved_preferences([candidate, active]) == {"tone": "gentle"}
    with pytest.raises(HTTPException):
        preference_tag("diagnosis", "anything")


@pytest.mark.parametrize(("hour", "expected"), [(23, False), (0, True), (12, True), (13, False)])
def test_followup_quiet_hours(hour: int, expected: bool) -> None:
    assert allowed_followup_time(datetime(2026, 9, 8, hour, tzinfo=UTC)) is expected


def test_timezone_required() -> None:
    with pytest.raises(ValidationError):
        FollowupIn(request_id="request1", topic="topic", due_at=datetime(2026, 10, 1))


@pytest.mark.asyncio
async def test_unbound_device_rejected() -> None:
    session = AsyncMock()
    session.scalar.return_value = Device(id=1, user_id=None)
    with pytest.raises(HTTPException) as error:
        await device_scope(session, "unknown")
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_create_retry_is_idempotent_and_conflict_rejected() -> None:
    due = datetime.now(UTC) + timedelta(days=1)
    row = CompanionFollowup(
        id="test", topic="topic", due_at=due, expires_at=due + timedelta(days=7), status="pending"
    )
    session = AsyncMock()
    session.scalar.side_effect = [Device(id=1, user_id=2), row]
    result = await create_followup(
        "device", FollowupIn(request_id="request1", topic="topic", due_at=due), session
    )
    assert result["id"] == "test"
    session.commit.assert_not_called()
    session.scalar.side_effect = [Device(id=1, user_id=2), row]
    with pytest.raises(HTTPException) as error:
        await create_followup(
            "device", FollowupIn(request_id="request1", topic="different", due_at=due), session
        )
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_terminal_transition_and_wrong_owner_filters() -> None:
    session = AsyncMock()
    row = CompanionFollowup(
        id="test",
        topic="topic",
        due_at=datetime.now(UTC),
        expires_at=datetime.now(UTC),
        status="cancelled",
    )
    session.scalar.return_value = row
    with pytest.raises(HTTPException) as error:
        await update_for_device(
            session, Device(id=1, user_id=2), "test", FollowupUpdate(status="completed")
        )
    assert error.value.status_code == 409
    statement = session.scalar.call_args.args[0]
    assert "user_id" in str(statement) and "device_id" in str(statement)
    session.scalar.return_value = None
    with pytest.raises(HTTPException) as error:
        await update_for_device(
            session, Device(id=1, user_id=3), "test", FollowupUpdate(status="cancelled")
        )
    assert error.value.status_code == 404

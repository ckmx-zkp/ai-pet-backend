"""模拟回执不得冒充实体播放，乱序/失败/超时必须停轮次。"""

import pytest

from web_api.social_test import RoomError, RoomStore


def test_eight_turns_and_idempotency() -> None:
    store = RoomStore()
    room = store.create("d8:85:ac:bb:b0:80")
    for i in range(1, 9):
        speaker = "virtual" if i % 2 else "real"
        result = "simulated" if i % 2 else "played"
        store.ack(room.room_id, str(i), speaker, result)
        store.ack(room.room_id, str(i), speaker, result)
    assert room.status == "finished"
    assert store.view(room)["next_turn"] is None
    assert len(room.receipts) == 8


def test_wrong_order_and_forged_virtual_receipt() -> None:
    store = RoomStore()
    room = store.create("d8:85:ac:bb:b0:80")
    for args in [("2", "real", "played"), ("1", "virtual", "played")]:
        with pytest.raises(RoomError):
            store.ack(room.room_id, *args)
    store.ack(room.room_id, "1", "virtual", "simulated")
    with pytest.raises(RoomError):
        store.ack(room.room_id, "2", "real", "simulated")
    with pytest.raises(RoomError):
        store.ack(room.room_id, "1", "virtual", "failed")


def test_timeout_failure_and_busy() -> None:
    store = RoomStore()
    room = store.create("d8:85:ac:bb:b0:80")
    with pytest.raises(RoomError):
        store.create(room.device_uid)
    store.ack(room.room_id, "1", "virtual", "failed")
    assert room.status == "failed"
    with pytest.raises(RoomError):
        store.ack(room.room_id, "2", "real", "played")
    expired = store.create(room.device_uid)
    expired.created_at -= 181
    assert store.get(expired.room_id).status == "expired"

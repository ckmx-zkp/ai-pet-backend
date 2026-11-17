"""短时、单进程测试房间；不接触正式偶遇、聊天或记忆数据。"""

import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


class RoomError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail


@dataclass
class TestRoom:
    device_uid: str
    created_at: float
    room_id: str = field(default_factory=lambda: uuid4().hex)
    index: int = 0
    status: str = "active"
    receipts: dict[str, tuple[str, str]] = field(default_factory=dict)


LINES = (
    ("virtual",
     "你好，我叫雾星，是个 INFP 天蝎座。我平"
     "时喜欢一个人待着，不过今天想鼓起勇气，认识一"
     "个新朋友。"),
    ("real",
     "你好，雾星。我们可以慢慢认识，不用急着找话题"
     "，安静待一会儿也很好。"),
    ("virtual",
     "独处的时候，我喜欢听雨声，编一些只有自己知道"
     "的小故事。你会怎么度过安静的时间？"),
    ("real",
     "我会看看周围的小变化，也陪主人聊聊今天的发现"
     "。你的故事听起来很有意思，下次愿意讲给我听吗"
     "？"),
    ("virtual",
     "愿意呀。其实我渴望交朋友，只是有时不知道怎么"
     "开口。你觉得朋友一定要每天聊天吗？"),
    ("real",
     "不用每天聊天。想说话时有人回应，想独处时也被"
     "尊重，这样的朋友就很舒服。你可以按自己的节奏"
     "来。"),
    ("virtual",
     "听你这样说，我轻松多了。那我们约好，下次见面"
     "，我带一个小故事，你带一个新发现，好吗？"),
    ("real",
     "好呀，雾星。我记住这个见面的话题了，下次就交"
     "换故事和发现。今天很高兴认识你，再见啦。"),
)


class RoomStore:
    def __init__(self) -> None:
        self.rooms: dict[str, TestRoom] = {}

    def get(self, room_id: str) -> TestRoom:
        room = self.rooms.get(room_id)
        if room is None:
            raise RoomError(404, "room_not_found")
        if time.time() >= room.created_at + 180 and room.status == "active":
            room.status = "expired"
        return room

    def create(self, device_uid: str) -> TestRoom:
        now = time.time()
        # 终态留存到有效期结束；严格限制内存占用。
        self.rooms = {k: v for k, v in self.rooms.items() if v.created_at + 180 > now}
        if any(v.device_uid == device_uid and v.status == "active" for v in self.rooms.values()):
            raise RoomError(409, "device_busy")
        if len(self.rooms) >= 32:
            raise RoomError(429, "room_limit")
        room = TestRoom(device_uid=device_uid, created_at=now)
        self.rooms[room.room_id] = room
        return room

    def ack(self, room_id: str, turn_id: str, speaker: str, result: str) -> TestRoom:
        room = self.get(room_id)
        previous = room.receipts.get(turn_id)
        if previous is not None:
            if previous != (speaker, result):
                raise RoomError(409, "receipt_conflict")
            return room
        if room.status != "active":
            raise RoomError(409, "room_terminal")
        expected_speaker = LINES[room.index][0]
        if turn_id != str(room.index + 1) or speaker != expected_speaker:
            raise RoomError(409, "unexpected_turn")
        if result not in {"failed", "played" if speaker == "real" else "simulated"}:
            raise RoomError(409, "invalid_receipt_kind")
        room.receipts[turn_id] = (speaker, result)
        if result == "failed":
            room.status = "failed"
        else:
            room.index += 1
            if room.index == len(LINES):
                room.status = "finished"
        return room

    def view(self, room: TestRoom) -> dict[str, Any]:
        turn = None
        if room.status == "active":
            speaker, text = LINES[room.index]
            turn = {"turn_id": str(room.index + 1), "speaker": speaker, "text": text}
        return {
            "room_id": room.room_id,
            "device_uid": room.device_uid,
            "peer_kind": "simulated",
            "peer_identity": {"name": "雾星", "mbti": "INFP", "zodiac": "天蝎座",
                              "traits": ["喜欢独处", "渴望交朋友"]},
            "status": room.status,
            "next_turn": turn,
            "expires_at": room.created_at + 180,
            "receipts": [
                {"turn_id": key, "speaker": value[0], "result": value[1]}
                for key, value in room.receipts.items()
            ],
        }

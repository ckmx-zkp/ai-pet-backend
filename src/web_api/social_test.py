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
    peer_device_uid: str | None = None
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


DUAL_LINES = (
    ("peer",
     "你好，我叫雾星。我有一点慢热，平时更喜欢独处"
     "。不过，今天想鼓起勇气，认识你。"),
    ("real",
     "你好，雾星。我们可以慢慢认识，不用急着找话题"
     "。安静待一会儿，也算一起玩呀。"),
    ("peer",
     "那我先分享一个小秘密。我喜欢听雨声，还会给路"
     "边的小树编故事。你喜欢什么？"),
    ("real",
     "我喜欢发现身边的小变化。比如一片新叶子，或者"
     "主人今天开心的瞬间。你编的故事，我也想听听。"),
    ("peer",
     "其实我很想交朋友，只是有时候想自己待着。朋友"
     "不常聊天，会不会慢慢变远呢？"),
    ("real",
     "不一定呀。想说话时认真回应，想独处时留一点空"
     "间，也可以是很好的朋友。你不用勉强自己。"),
    ("peer",
     "听你这样说，我轻松多了。那下次见面，我带一个"
     "小故事，你带一个新发现，好不好？"),
    ("real",
     "好呀，雾星。下次我们就交换故事和发现。今天很"
     "高兴认识你，先说再见啦。"),
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

    def create(self, device_uid: str, peer_device_uid: str | None = None) -> TestRoom:
        now = time.time()
        # 终态留存到有效期结束；严格限制内存占用。
        self.rooms = {k: v for k, v in self.rooms.items() if v.created_at + 180 > now}
        requested = {device_uid, peer_device_uid} - {None}
        if peer_device_uid == device_uid:
            raise RoomError(409, "same_device")
        if any(v.status == "active" and requested.intersection({v.device_uid, v.peer_device_uid})
               for v in self.rooms.values()):
            raise RoomError(409, "device_busy")
        if len(self.rooms) >= 32:
            raise RoomError(429, "room_limit")
        room = TestRoom(device_uid=device_uid, created_at=now, peer_device_uid=peer_device_uid)
        self.rooms[room.room_id] = room
        return room

    def ack(self, room_id: str, turn_id: str, speaker: str, result: str,
            actor_device_uid: str | None = None) -> TestRoom:
        room = self.get(room_id)
        if room.peer_device_uid:
            expected_uid = {"real": room.device_uid, "peer": room.peer_device_uid}.get(speaker)
            if expected_uid is None or actor_device_uid != expected_uid:
                raise RoomError(409, "wrong_actor")
        previous = room.receipts.get(turn_id)
        if previous is not None:
            if previous != (speaker, result):
                raise RoomError(409, "receipt_conflict")
            return room
        if room.status != "active":
            raise RoomError(409, "room_terminal")
        lines = DUAL_LINES if room.peer_device_uid else LINES
        expected_speaker = lines[room.index][0]
        if turn_id != str(room.index + 1) or speaker != expected_speaker:
            raise RoomError(409, "unexpected_turn")
        if result not in {"failed", "played" if speaker in {"real", "peer"} else "simulated"}:
            raise RoomError(409, "invalid_receipt_kind")
        room.receipts[turn_id] = (speaker, result)
        if result == "failed":
            room.status = "failed"
        else:
            room.index += 1
            if room.index == len(lines):
                room.status = "finished"
        return room

    def view(self, room: TestRoom) -> dict[str, Any]:
        turn = None
        if room.status == "active":
            speaker, text = (DUAL_LINES if room.peer_device_uid else LINES)[room.index]
            turn = {"turn_id": str(room.index + 1), "speaker": speaker, "text": text}
            if room.peer_device_uid:
                turn["device_uid"] = room.peer_device_uid if speaker == "peer" else room.device_uid
        return {
            "room_id": room.room_id,
            "device_uid": room.device_uid,
            "peer_kind": "real" if room.peer_device_uid else "simulated",
            "peer_device_uid": room.peer_device_uid,
            "peer_identity": {"name": "雾星", "mbti": "INFP", "zodiac": "天蝎座",
                              "traits": ["喜欢独处", "渴望交朋友"]},
            "status": room.status,
            "next_turn": turn,
            "expires_at": room.created_at + 180,
            "receipts": [
                {"turn_id": key, "speaker": value[0], "result": value[1],
                 "actor_device_uid": (room.peer_device_uid if value[0] == "peer"
                                      else room.device_uid if value[0] == "real" else None)}
                for key, value in room.receipts.items()
            ],
        }

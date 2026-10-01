"""阀门指令队列与已应用检查点。

指令带单调序号入队；推进时只执行序号大于检查点的指令，每执行一条就把新的已
应用序号落盘。检查点只留在内存里的话，重启后队列从零开始，旧指令会被重放，
阀门回到调节前的位置——这正是要避免的。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..store.command import CommandCheckpoint
from ..store.state import DurableState
from .move import move_valve
from .valve import Valve


@dataclass(frozen=True)
class ValveCommand:
    """一条阀门指令。"""

    seq: int
    target_pct: float
    source: str

    def as_dict(self) -> dict:
        return {"seq": self.seq, "target_pct": round(self.target_pct, 2), "source": self.source}


class ValveCommandQueue:
    """按序号排列的阀门指令队列。"""

    def __init__(self, name: str) -> None:
        self._name = name
        self._commands: list[ValveCommand] = []
        self._next_seq = 1

    @property
    def name(self) -> str:
        return self._name

    def enqueue(self, target_pct: float, source: str = "dispatch") -> ValveCommand:
        """入队一条指令，返回带序号的指令。"""

        command = ValveCommand(self._next_seq, float(target_pct), str(source))
        self._commands.append(command)
        self._next_seq += 1
        return command

    def commands(self) -> list[ValveCommand]:
        """返回全部指令（按序号升序）。"""

        return list(self._commands)

    def pending(self, applied: int) -> list[ValveCommand]:
        """返回序号大于检查点的指令。"""

        return [command for command in self._commands if command.seq > int(applied)]

    def last_seq(self) -> int:
        """返回队尾序号。"""

        return self._commands[-1].seq if self._commands else 0


def replay_queue(
    valve: Valve,
    durable: DurableState,
    queue: ValveCommandQueue,
    checkpoint: CommandCheckpoint,
) -> dict:
    """按检查点推进队列，逐条落盘检查点，返回本次推进摘要。"""

    applied = checkpoint.load(queue.name)
    pending = queue.pending(applied)
    moves: list[dict] = []
    for command in pending:
        move = move_valve(valve, durable, command.target_pct)
        checkpoint.save(queue.name, command.seq)
        applied = command.seq
        moves.append({**command.as_dict(), **move.as_dict()})
    return {
        "queue": queue.name,
        "applied": applied,
        "last_seq": queue.last_seq(),
        "skipped": len(queue.commands()) - len(pending),
        "replayed": len(pending),
        "moves": moves,
    }

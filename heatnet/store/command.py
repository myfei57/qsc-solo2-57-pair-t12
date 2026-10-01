"""阀门指令队列的检查点存储。

队列把"最后一条已应用指令的序号"单独落盘。重启后先读这个检查点，序号不大于
检查点的指令一律跳过——否则队列从零开始重放，已执行的指令会被再执行一次，阀门
回到调节前的位置。检查点写失败必须向上抛出，调用方据此拒绝本次推进。
"""

from __future__ import annotations

from .jsonfile import JsonStore


class CommandCheckpoint:
    """按队列名保存已应用序号。"""

    def __init__(self, store: JsonStore, prefix: str = "command") -> None:
        self._store = store
        self._prefix = prefix.strip("/")

    @property
    def store(self) -> JsonStore:
        return self._store

    def doc_id(self, queue: str) -> str:
        """返回某队列检查点文档的标识。"""

        return f"{self._prefix}/{queue}"

    def load(self, queue: str) -> int:
        """读取已应用序号，缺失或非法时返回 ``0``。"""

        raw = self._store.read(self.doc_id(queue))
        if isinstance(raw, dict):
            try:
                return max(0, int(raw.get("applied", 0)))
            except (TypeError, ValueError):
                return 0
        return 0

    def save(self, queue: str, applied: int) -> str:
        """保存已应用序号，返回落盘路径。"""

        if applied < 0:
            raise ValueError("已应用序号不能为负")
        return self._store.write(self.doc_id(queue), {"applied": int(applied)})

    def reset(self, queue: str) -> bool:
        """清除检查点，返回是否真的删掉了文件。"""

        return self._store.remove(self.doc_id(queue))

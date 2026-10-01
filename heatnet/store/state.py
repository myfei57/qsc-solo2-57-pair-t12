"""设备当前态的持久化封装。

每次阀门动作都要先把新位置写进"当前态"文档，再改内存——顺序反了就会出现内存
与磁盘不一致：进程重启从盘上加载后，阀门回退到旧值。这里把文档标识与载荷形状
固定下来，让调用点只需要关心"写成功没有"。
"""

from __future__ import annotations

from typing import Any

from .jsonfile import JsonStore


class DurableState:
    """按组件写读当前态的薄封装。"""

    def __init__(self, store: JsonStore, prefix: str = "state") -> None:
        self._store = store
        self._prefix = prefix.strip("/")

    @property
    def store(self) -> JsonStore:
        return self._store

    def doc_id(self, component: str) -> str:
        """返回某组件当前态文档的标识。"""

        return f"{self._prefix}/{component}"

    def load(self, component: str) -> dict:
        """读取组件当前态；文件缺失或内容不是映射时返回空字典。"""

        raw = self._store.read(self.doc_id(component))
        if isinstance(raw, dict):
            return raw
        return {}

    def save(self, component: str, payload: Any) -> str:
        """写入组件当前态，返回落盘路径。"""

        if not isinstance(payload, dict):
            raise ValueError("当前态载荷必须是映射")
        return self._store.write(self.doc_id(component), payload)

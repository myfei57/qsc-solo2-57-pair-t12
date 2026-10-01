"""调度链拓扑。

控制链是「气象/负荷 → 热源 → 换热站 → 阀门/泵 → 热量 → 审计」，每一步都依赖
前一步完成。:class:`Topology` 保存这条依赖链，操作前用 ``verify`` 检查某个阶段
的前驱是否都已完成，未完成即返回缺失项（由调用方决定是拒绝还是记录告警）。
"""

from __future__ import annotations

from dataclasses import dataclass

STAGES: tuple[str, ...] = ("weather", "source", "station", "actuator", "quota", "audit")


@dataclass(frozen=True)
class Stage:
    """一个调度阶段及其前置阶段。"""

    name: str
    label: str
    requires: tuple[str, ...]

    def as_dict(self) -> dict:
        return {"name": self.name, "label": self.label, "requires": list(self.requires)}


class Topology:
    """阶段依赖链。"""

    def __init__(self, stages: tuple[Stage, ...]) -> None:
        self._stages = stages
        self._index = {stage.name: stage for stage in stages}

    def stage(self, name: str) -> Stage:
        """按名字取阶段，不存在时抛出 ``KeyError``。"""

        return self._index[name]

    def order(self) -> list[str]:
        """返回阶段顺序。"""

        return [stage.name for stage in self._stages]

    def predecessors(self, name: str) -> tuple[str, ...]:
        """返回某阶段的直接前置阶段。"""

        return self.stage(name).requires

    def verify(self, completed: set[str]) -> dict:
        """检查每个阶段的直接前置是否都已完成。"""

        missing: dict[str, list[str]] = {}
        for stage in self._stages:
            gaps = [item for item in self.predecessors(stage.name) if item not in completed]
            if gaps:
                missing[stage.name] = gaps
        return {"ok": not missing, "missing": missing, "completed": sorted(completed)}

    def downstream(self, name: str) -> list[str]:
        """返回某阶段的所有下游阶段（按链路顺序）。"""

        found: list[str] = []
        frontier = [name]
        while frontier:
            current = frontier.pop(0)
            for stage in self._stages:
                if current in stage.requires and stage.name not in found:
                    found.append(stage.name)
                    frontier.append(stage.name)
        return found

    def summary(self) -> dict:
        """汇总拓扑，供状态快照与控制台读取。"""

        return {"order": self.order(), "stages": [stage.as_dict() for stage in self._stages]}


def build_default_topology() -> Topology:
    """构造默认的调度链拓扑。"""

    return Topology(
        (
            Stage("weather", "气象/负荷", ()),
            Stage("source", "热源", ("weather",)),
            Stage("station", "换热站", ("source",)),
            Stage("actuator", "阀门/泵", ("station",)),
            Stage("quota", "热量", ("actuator",)),
            Stage("audit", "审计", ("quota",)),
        )
    )

"""供热分区命名空间与调度链拓扑。

命名空间把 ``区域.设备`` 映射到设备类型，控制台与审计共用同一套名字；分区表
同时维护"分区 → 站列表"和"站 → 分区"两份索引，任何一次拆分都必须把两份索引
一起更新；拓扑描述「气象/负荷 → 热源 → 换热站 → 阀门/泵 → 热量 → 审计」这条
硬顺序链，用来在操作前检查工位是否满足前一阶段已完成。
"""

from __future__ import annotations

from .registry import Device, NamespaceRegistry
from .topology import STAGES, Stage, Topology, build_default_topology
from .zone import Zone, ZoneRegistry

__all__ = [
    "Device",
    "NamespaceRegistry",
    "STAGES",
    "Stage",
    "Topology",
    "build_default_topology",
    "Zone",
    "ZoneRegistry",
]

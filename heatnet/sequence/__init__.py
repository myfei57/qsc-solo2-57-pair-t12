"""跨组件操作编排。

每个操作都是真实的跨模块调用链，顺序在编排里写死：

- 投运：气象推送 → **曲线更新** → 热源调质 → 调量 → 一次网跟随 → 补水定压 → 循环；
- 调度：按分区排优先级 → 一次网按站分配流量 → 换热站批量下发；
- 停运：先停泵再关阀 → 撤销一次网流量 → 热源停机。

顺序被破坏时报告里的 ``violations`` 会点出来，由平台写审计。
"""

from __future__ import annotations

from .dispatch import dispatch_demand, recalibrate_flow
from .heating import advance_heating
from .shutdown import shutdown_plant
from .startup import startup_plant

__all__ = ["advance_heating", "dispatch_demand", "recalibrate_flow", "shutdown_plant", "startup_plant"]

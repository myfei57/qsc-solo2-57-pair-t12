"""调节优先级排序。

按设定点从高到低排：设定点高的站离热源近、管容小，先动它们对末端影响最小。
排序只产出顺序，不碰任何设备状态，供调度编排按序下发。
"""

from __future__ import annotations


def priority_order(entries: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """按设定点降序排序，设定点相同时按站名升序。"""

    return sorted(entries, key=lambda item: (-float(item[1]), str(item[0])))

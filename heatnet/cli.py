"""命令行入口。

五个子命令覆盖日常使用：

``serve``   启动控制台 HTTP 服务，可选地在启动后探测接口；
``demo``    在本地跑一遍完整流程（气象推送 → 调质调量 → 投运 → 调度下发 →
            控制周期 → 流量标定 → 定压改造 → 二次网循环 → 热量采集与结算 →
            分区拆分 → 阀门队列回放 → 停机与复位），用于交付前的真实运行检查；
``status``  打印当前状态快照；
``config``  打印生效配置；
``reset``   清掉落盘的平台计数。
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from .app import Platform, build_platform
from .clock import ManualClock, SystemClock
from .config import config_to_mapping, default_config, load_config
from .console.server import ConsoleServer, probe_endpoints
from .errors import PlantError

DEFAULT_PROBE_PATHS = (
    "/api/status",
    "/api/readiness",
    "/api/topology",
    "/api/audit",
    "/api/stations",
    "/api/quota",
)


def _build(args: argparse.Namespace) -> Platform:
    config = load_config(args.config) if getattr(args, "config", None) else default_config()
    if getattr(args, "storage_root", None):
        return build_platform(config, storage_root=args.storage_root)
    return Platform(config=config)


def _dump(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _cmd_serve(args: argparse.Namespace) -> int:
    platform = _build(args)
    server = ConsoleServer(platform, host=args.host, port=args.port)
    base_url = server.start()
    payload: dict = {"listening": base_url, "routes": server.api.routes()}
    if args.probe:
        payload["probe"] = probe_endpoints(base_url, list(DEFAULT_PROBE_PATHS))
    _dump(payload)
    if args.duration > 0:
        try:
            time.sleep(args.duration)
        except KeyboardInterrupt:  # pragma: no cover - 交互路径
            pass
        server.stop()
        return 0
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:  # pragma: no cover - 交互路径
        server.stop()
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    clock = ManualClock() if args.fast else SystemClock()
    config_path = getattr(args, "config", None)
    config = load_config(config_path) if config_path else default_config()
    platform = build_platform(config, clock=clock, storage_root=getattr(args, "storage_root", None))

    # 演示从干净基线起步：先清掉上一轮落盘的平台计数，并解除上一轮演示结束时
    # 留下的停机保护，否则这一次会直接从带故障的状态起跑。
    platform.reset_state()
    if platform.source.state() == "tripped":
        platform.reset_source("demo-baseline")

    startup = platform.start()
    weather = platform.push_weather(args.outdoor_c, "demo-weather")
    launch = platform.startup(args.outdoor_c, args.demand_pct, "demo-operator")
    preview = platform.plan_preview(args.demand_pct)
    dispatch = platform.dispatch(args.demand_pct, args.target_c, None, None)
    cycles = [platform.cycle(dt=args.dt) for _ in range(args.cycles)]
    calibration = platform.calibrate_flow(args.baseline_t_h)
    retrofit = platform.retrofit_baseline(args.baseline_kpa)
    secondary = platform.secondary_cycle(args.dt)
    heat = [platform.collect_heat(name, args.sample_mwh) for name in platform.meter_names()]
    settled = platform.settle_quota()
    split = platform.split_zone(args.split_zone, args.split_stations, args.new_zone)
    queued = platform.queue_commands(args.station, [55.0, 62.0], "demo-operator")
    replayed = platform.replay_valves([args.station])
    disturbance = platform.disturb_secondary(args.disturb)
    concurrency = platform.concurrency_probe(rounds=args.rounds)
    trip = platform.trip("demo-complete")
    reset = platform.reset_source("demo-operator")

    # 演示自检用临时端口，避免和本机常驻服务抢 8080。
    server = ConsoleServer(platform, port=0)
    base_url = server.start()
    probe = probe_endpoints(base_url, list(DEFAULT_PROBE_PATHS))
    server.stop()

    report = {
        "startup": startup,
        "weather": {key: weather[key] for key in ("ok", "outdoor_c", "supply_c", "epoch", "violations")},
        "launch": {key: launch[key] for key in ("ok", "stage", "flow_t_h", "supply_c", "violations")},
        "preview": preview[:3],
        "dispatch": {
            key: dispatch[key]
            for key in ("ok", "planned", "adjusted", "target_c", "flow_t_h", "threshold_t_h", "violations")
        },
        "cycles_run": len(cycles),
        "last_cycle": cycles[-1],
        "calibration": calibration,
        "retrofit": retrofit,
        "secondary": {key: secondary[key] for key in ("ok", "flow_t_h", "pump_idle", "violations")},
        "heat": heat,
        "settled": settled,
        "split": split,
        "queued": queued,
        "replayed": {key: replayed[key] for key in ("ok", "replayed", "applied")},
        "disturbance": disturbance,
        "concurrency": concurrency,
        "trip": {key: trip[key] for key in ("ok", "state", "reason", "trips")},
        "reset": {key: reset[key] for key in ("ok", "state")},
        "probe": probe,
        "status": platform.status(),
    }
    _dump(report)

    failures = [name for name, item in probe.items() if not item["ok"]]
    for name, operation in (
        ("weather", weather),
        ("launch", launch),
        ("dispatch", dispatch),
        ("secondary", secondary),
        ("retrofit", retrofit),
        ("concurrency", concurrency),
    ):
        if not operation.get("ok"):
            failures.extend(f"{name}:{item}" for item in operation.get("violations", []))
    if failures:
        print(f"检查未通过: {failures}", file=sys.stderr)
        return 1
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    platform = _build(args)
    payload = platform.status()
    payload["topology"] = platform.topology.summary()
    payload["namespaces"] = platform.namespaces.describe()
    payload["trend"] = platform.trend.snapshot()
    payload["forecast"] = platform.outdoor_forecast(None, steps=4)
    _dump(payload)
    return 0


def _cmd_config(args: argparse.Namespace) -> int:
    config_path = getattr(args, "config", None)
    config = load_config(config_path) if config_path else default_config()
    _dump(config_to_mapping(config))
    return 0


def _cmd_reset(args: argparse.Namespace) -> int:
    platform = _build(args)
    removed = platform.reset_state()
    _dump({"storage_root": platform.store.root, "platform_state_removed": removed})
    return 0


def build_parser() -> argparse.ArgumentParser:
    """构造命令行解析器。"""

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", help="JSON 配置文件路径", default=argparse.SUPPRESS)
    common.add_argument("--storage-root", help="覆盖状态存储目录", default=argparse.SUPPRESS)
    parser = argparse.ArgumentParser(
        prog="heatnet", description="工业过程顺序与联锁控制服务", parents=[common]
    )
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="启动控制台服务", parents=[common])
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    serve.add_argument("--duration", type=float, default=0.0, help="运行多少秒后退出，0 表示常驻")
    serve.add_argument("--probe", action="store_true", help="启动后探测接口")
    serve.set_defaults(func=_cmd_serve)

    demo = sub.add_parser("demo", help="跑一遍完整流程", parents=[common])
    demo.add_argument("--outdoor-c", type=float, default=-5.0, help="演示用的室外温度 (℃)")
    demo.add_argument("--demand-pct", type=float, default=60.0, help="演示用的负荷需求 (%)")
    demo.add_argument("--target-c", type=float, default=60.0, help="演示用的二次侧设定点 (℃)")
    demo.add_argument("--cycles", type=int, default=240, help="演示控制周期数")
    demo.add_argument("--dt", type=float, default=1.0, help="控制周期步长（秒）")
    demo.add_argument("--rounds", type=int, default=24, help="并发探测轮数")
    demo.add_argument("--baseline-t-h", type=float, default=2500.0, help="演示用的实测流量 (t/h)")
    demo.add_argument("--baseline-kpa", type=float, default=340.0, help="演示用的定压基线 (kPa)")
    demo.add_argument("--sample-mwh", type=float, default=12.5, help="每次热量采集的增量 (MWh)")
    demo.add_argument("--disturb", type=float, default=0.4, help="演示用的二次网热负荷扰动系数")
    demo.add_argument("--station", default="st01", help="演示用的换热站")
    demo.add_argument("--split-zone", default="north", help="演示拆分源分区")
    demo.add_argument("--new-zone", default="north-west", help="演示拆分出的新分区")
    demo.add_argument("--split-stations", nargs="*", default=["st02", "st03"], help="划入新分区的站")
    demo.add_argument("--fast", action="store_true", help="使用可推进时钟，跳过真实等待")
    demo.set_defaults(func=_cmd_demo)

    status = sub.add_parser("status", help="打印状态快照", parents=[common])
    status.set_defaults(func=_cmd_status)

    config = sub.add_parser("config", help="打印生效配置", parents=[common])
    config.set_defaults(func=_cmd_config)

    reset = sub.add_parser("reset", help="清掉落盘的平台计数", parents=[common])
    reset.set_defaults(func=_cmd_reset)
    return parser


def main(argv: list[str] | None = None) -> int:
    """命令行主入口。"""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except PlantError as error:
        print(json.dumps(error.as_record(), ensure_ascii=False), file=sys.stderr)
        return 2

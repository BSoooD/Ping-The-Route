#!/usr/bin/env python3

import subprocess
import platform
import socket
import re
import time
import threading
from dataclasses import dataclass, field
from typing import List, Optional

try:
    from ping3 import ping
except ImportError:
    raise RuntimeError("Missing dependency: ping3 (pip install ping3)")

try:
    import yaml
except ImportError:
    raise RuntimeError("Missing dependency: pyyaml (pip install pyyaml)")


# =========================
# Data models
# =========================

@dataclass
class PingStats:
    sent: int
    received: int
    loss_pct: float
    min_ms: Optional[float]
    avg_ms: Optional[float]
    max_ms: Optional[float]
    rtts_ms: List[float] = field(default_factory=list)


@dataclass
class Hop:
    hop: int
    ip: Optional[str]
    hostname: Optional[str] = None
    ping: Optional[PingStats] = None


@dataclass
class RouteResult:
    target: str
    target_ip: Optional[str]
    hops: List[Hop]


# =========================
# Traceroute helpers
# =========================

IP_REGEX = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})")


def get_traceroute_command(target: str, resolve_dns: bool) -> List[str]:
    system = platform.system().lower()
    if system == "windows":
        cmd = ["tracert"]
        if not resolve_dns:
            cmd.append("-d")
        cmd.append(target)
    else:
        cmd = ["traceroute"]
        if not resolve_dns:
            cmd.append("-n")
        cmd.append(target)
    return cmd


def parse_ip_from_line(line: str) -> Optional[str]:
    match = IP_REGEX.search(line)
    return match.group(1) if match else None


def reverse_dns(ip: str) -> Optional[str]:
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return None


def run_traceroute(target: str, resolve_dns_during: bool) -> List[Hop]:
    cmd = get_traceroute_command(target, resolve_dns_during)
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )

    hops: List[Hop] = []

    for line in process.stdout:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if not parts or not parts[0].isdigit():
            continue
        hop_num = int(parts[0])
        ip = parse_ip_from_line(line)
        hops.append(Hop(hop=hop_num, ip=ip))

    process.wait()
    return hops


# =========================
# Pinger
# =========================

def ping_host(ip: str, count: int = 3, timeout: float = 1.0, interval: float = 0.5) -> PingStats:
    rtts: List[float] = []
    sent = count
    for _ in range(count):
        rtt = ping(ip, timeout=timeout, unit="ms")
        if rtt is not None:
            rtts.append(rtt)
        time.sleep(interval)
    received = len(rtts)
    loss_pct = ((sent - received) / sent) * 100.0
    if rtts:
        min_ms = min(rtts)
        avg_ms = sum(rtts) / len(rtts)
        max_ms = max(rtts)
    else:
        min_ms = avg_ms = max_ms = None
    return PingStats(sent, received, loss_pct, min_ms, avg_ms, max_ms, rtts)


def live_ping(ip: str, interval: float = 1.0, timeout: float = 1.0, stop_event: threading.Event = None):
    """
    Continuously ping the IP, printing RTTs live until stop_event is set.
    """
    while stop_event is None or not stop_event.is_set():
        rtt = ping(ip, unit="ms", timeout=timeout)
        if rtt is not None:
            print(f"\rLive ping {ip}: {rtt:.1f} ms", end="")
        else:
            print(f"\rLive ping {ip}: timeout", end="")
        time.sleep(interval)
    print("")  # move to next line when stopping


# =========================
# YAML export helpers
# =========================

def dataclass_to_dict(obj):
    """
    Recursively convert dataclasses to dicts for YAML dumping.
    """
    if hasattr(obj, "__dataclass_fields__"):
        result = {}
        for field_name in obj.__dataclass_fields__:
            value = getattr(obj, field_name)
            result[field_name] = dataclass_to_dict(value)
        return result
    elif isinstance(obj, list):
        return [dataclass_to_dict(item) for item in obj]
    else:
        return obj


def export_to_yaml(route_result: RouteResult, filename: str):
    data = dataclass_to_dict(route_result)
    with open(filename, "w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False, allow_unicode=True)
    print(f"\nSaved route info to {filename}")



def ping_the_route(
    target: str,
    resolve_dns_during_trace: bool = False,
    resolve_hostnames_after: bool = False,
    ping_count: int = 3,
    live_ping_final: bool = True
) -> RouteResult:
    try:
        target_ip = socket.gethostbyname(target)
    except Exception:
        target_ip = None

    stop_event = threading.Event()
    live_thread = None

    if live_ping_final and target_ip:
        live_thread = threading.Thread(target=live_ping, args=(target_ip, 1.0, 1.0, stop_event))
        live_thread.daemon = True
        live_thread.start()

    hops = run_traceroute(target, resolve_dns_during_trace)

    for hop in hops:
        if hop.ip:
            hop.ping = ping_host(hop.ip, count=ping_count)
            if resolve_hostnames_after:
                hop.hostname = reverse_dns(hop.ip)

    if live_thread:
        stop_event.set()
        live_thread.join()

    return RouteResult(target=target, target_ip=target_ip, hops=hops)


# =========================
# CLI entry point
# =========================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ping The Route – Live + YAML")
    parser.add_argument("target", help="IP or domain")
    parser.add_argument("--resolve-during", action="store_true", help="Resolve DNS during traceroute")
    parser.add_argument("--resolve-after", action="store_true", help="Resolve hostnames after traceroute")
    parser.add_argument("-c", "--count", type=int, default=3, help="Ping count per hop")
    parser.add_argument("--no-live", action="store_true", help="Disable live ping of target")
    parser.add_argument("-o", "--output", type=str, help="Save results to YAML file")

    args = parser.parse_args()

    result = ping_the_route(
        target=args.target,
        resolve_dns_during_trace=args.resolve_during,
        resolve_hostnames_after=args.resolve_after,
        ping_count=args.count,
        live_ping_final=not args.no_live
    )

    print(f"\nRoute to {result.target} ({result.target_ip})\n")

    for hop in result.hops:
        if hop.ping and hop.ping.received > 0:
            print(
                f"{hop.hop:2d}  {hop.ip:15s}  "
                f"{hop.ping.avg_ms:.1f} ms  "
                f"loss {hop.ping.loss_pct:.0f}%"
            )
        else:
            print(f"{hop.hop:2d}  {hop.ip}  no response")

    if args.output:
        export_to_yaml(result, args.output)

#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import time
import subprocess
import platform
import socket
import re
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
    live_rtt: Optional[float] = None


@dataclass
class RouteResult:
    target: str
    target_ip: Optional[str]
    hops: List[Hop]


# =========================
# Traceroute helpers
# =========================

IP_REGEX = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})")


def get_traceroute_command(target: str, resolve_dns: bool) -> list:
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
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="ignore"
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
        avg_ms = sum(rtts)/len(rtts)
        max_ms = max(rtts)
    else:
        min_ms = avg_ms = max_ms = None
    return PingStats(sent, received, loss_pct, min_ms, avg_ms, max_ms, rtts)


def live_ping(hop: Hop, interval: float = 1.0, stop_event: threading.Event = None):
    while stop_event is None or not stop_event.is_set():
        if hop.ip:
            rtt = ping(hop.ip, unit="ms", timeout=1.0)
            hop.live_rtt = rtt
        time.sleep(interval)


# =========================
# YAML export
# =========================

def dataclass_to_dict(obj):
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
    messagebox.showinfo("Saved", f"Route info saved to {filename}")


# =========================
# GUI
# =========================

class PingTheRouteGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Ping The Route")
        self.route_result: Optional[RouteResult] = None
        self.stop_event = threading.Event()
        self.live_threads: List[threading.Thread] = []

        # Input frame
        frame = ttk.Frame(root)
        frame.pack(padx=10, pady=10, fill="x")

        ttk.Label(frame, text="Target IP/Domain:").pack(side="left")
        self.target_entry = ttk.Entry(frame)
        self.target_entry.pack(side="left", fill="x", expand=True, padx=5)
        self.start_button = ttk.Button(frame, text="Start", command=self.start_traceroute)
        self.start_button.pack(side="left", padx=5)
        self.save_button = ttk.Button(frame, text="Save YAML", command=self.save_yaml, state="disabled")
        self.save_button.pack(side="left", padx=5)

        # Treeview for hops
        columns = ("hop", "ip", "hostname", "avg_rtt", "loss", "live_rtt")
        self.tree = ttk.Treeview(root, columns=columns, show="headings", height=20)
        for col in columns:
            self.tree.heading(col, text=col)
            if col in ("avg_rtt", "live_rtt"):
                self.tree.column(col, width=80, anchor="center")
            else:
                self.tree.column(col, width=120, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)

        # style tags
        self.tree.tag_configure("timeout", foreground="red")
        self.tree.tag_configure("fast", background="#c6f5c6")   # green
        self.tree.tag_configure("medium", background="#f5f3c6") # yellow
        self.tree.tag_configure("slow", background="#f5c6c6")   # red

        self.update_gui_loop()

    def start_traceroute(self):
        target = self.target_entry.get().strip()
        if not target:
            messagebox.showerror("Error", "Please enter a target IP or domain")
            return
        self.start_button.config(state="disabled")
        self.save_button.config(state="disabled")
        self.stop_event.clear()
        threading.Thread(target=self.run_traceroute_thread, args=(target,), daemon=True).start()

    def run_traceroute_thread(self, target):
        try:
            try:
                target_ip = socket.gethostbyname(target)
            except Exception:
                target_ip = None
            hops = run_traceroute(target, resolve_dns_during=False)
            self.route_result = RouteResult(target=target, target_ip=target_ip, hops=hops)
            # start live ping for each hop
            for hop in hops:
                t = threading.Thread(target=live_ping, args=(hop,1.0,self.stop_event), daemon=True)
                t.start()
                self.live_threads.append(t)
            # per-hop ping stats
            for hop in hops:
                if hop.ip:
                    hop.ping = ping_host(hop.ip,count=3)
                    hop.hostname = reverse_dns(hop.ip)
            self.save_button.config(state="normal")
        finally:
            self.start_button.config(state="normal")
            self.stop_event.set()

    def update_gui_loop(self):
        self.tree.delete(*self.tree.get_children())
        if self.route_result:
            for hop in self.route_result.hops:
                avg_rtt_val = hop.ping.avg_ms if hop.ping and hop.ping.avg_ms is not None else None
                loss_val = hop.ping.loss_pct if hop.ping and hop.ping.loss_pct is not None else None
                live_rtt_val = hop.live_rtt

                avg_rtt = f"{avg_rtt_val:.1f}" if avg_rtt_val is not None else "timeout"
                loss = f"{loss_val:.0f}%" if loss_val is not None else "timeout"
                live_rtt = f"{live_rtt_val:.1f}" if live_rtt_val is not None else "timeout"

                # insert
                item_id = self.tree.insert("", "end", values=(hop.hop, hop.ip, hop.hostname, avg_rtt, loss, live_rtt))

                # color coding RTTs
                def color_rtt(value):
                    if value == "timeout" or value is None:
                        return "timeout"
                    elif value < 50:
                        return "fast"
                    elif value < 150:
                        return "medium"
                    else:
                        return "slow"

                self.tree.item(item_id, tags=(color_rtt(avg_rtt_val),))

        self.root.after(500, self.update_gui_loop)

    def save_yaml(self):
        if not self.route_result:
            return
        filename = filedialog.asksaveasfilename(defaultextension=".yml", filetypes=[("YAML files","*.yml")])
        if filename:
            export_to_yaml(self.route_result, filename)


if __name__ == "__main__":
    root = tk.Tk()
    gui = PingTheRouteGUI(root)
    root.mainloop()

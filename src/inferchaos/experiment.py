"""Fault experiments against mock providers behind llmgateway (CONCEPTS.md sections 3-5).

Providers are tokenbench mock servers in subprocesses (so one can be killed). The gateway runs
in a thread. A steady open-loop load records one SLO event per request; a fault is injected for
a window; the gateway's breaker state is sampled throughout. The summary scores the fault the
SRE way: budget burned, peak burn rate, alerts, recovery time."""

from __future__ import annotations

import asyncio
import json
import re
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field

import httpx

from inferchaos.slo import (
    SLO,
    Event,
    alerts_fired,
    budget_consumed,
    burn_rate_series,
    recovery_time,
)

RULES = [{"name": "page", "long_s": 30, "short_s": 5, "burn": 14.4}, {"name": "ticket", "long_s": 60, "short_s": 10, "burn": 3}]
_BREAKER = re.compile(r'llmgateway_breaker_state\{provider="([^"]+)"\} (\d)')
_COUNTER = re.compile(r'llmgateway_(\w+)_total\{(?:provider|from|tenant)="([^"]+)"\} (\d+)')
_STATE = {0: "closed", 1: "open", 2: "half_open"}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_health(url: str, timeout: float = 20) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{url}/health", timeout=0.5).status_code == 200:
                return True
        except httpx.HTTPError:
            time.sleep(0.05)
    return False


@dataclass
class Providers:
    """N mock providers as subprocesses; each can be throttled at runtime or killed and restarted."""
    n: int = 2
    capacity: int = 16
    ttft_ms: float = 40
    itl_ms: float = 2
    procs: dict[str, subprocess.Popen] = field(default_factory=dict)
    urls: dict[str, str] = field(default_factory=dict)

    @property
    def names(self) -> list[str]:
        return [f"p{i}" for i in range(self.n)]

    def _spawn(self, name: str) -> None:
        port = int(self.urls[name].rsplit(":", 1)[1]) if name in self.urls else _free_port()
        cmd = [sys.executable, "-m", "tokenbench.mockserver", "--port", str(port), "--capacity", str(self.capacity),
               "--ttft-ms", str(self.ttft_ms), "--itl-ms", str(self.itl_ms)]
        self.procs[name] = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.urls[name] = f"http://127.0.0.1:{port}"
        assert _wait_health(self.urls[name]), f"{name} did not start"

    def start(self) -> None:
        for n in self.names:
            self._spawn(n)

    def stop(self) -> None:
        for p in self.procs.values():
            if p.poll() is None:
                p.terminate()
        for p in self.procs.values():
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()

    def throttle(self, name: str, extra_latency_ms: float) -> None:
        httpx.post(f"{self.urls[name]}/admin/config", json={"extra_latency_ms": extra_latency_ms}, timeout=5)

    def kill(self, name: str) -> None:
        self.procs[name].kill()
        self.procs[name].wait(timeout=5)

    def restart(self, name: str) -> None:
        self._spawn(name)


class Experiment:
    def __init__(self, providers: Providers, slo: SLO, rate: float = 4.0, slo_ttft_ms: float = 800, tenant_rate: float = 1000,
                 tenant_burst: float = 1000, breaker_min_samples: int = 10, breaker_window_s: float = 15, breaker_cooldown_s: float = 5,
                 max_tokens: int = 24):
        self.p, self.slo, self.rate, self.max_tokens = providers, slo, rate, max_tokens
        from llmgateway.app import GatewayConfig, ProviderConfig
        self.cfg = GatewayConfig(
            providers={n: ProviderConfig(name=n, base_url=u, model="mock") for n, u in providers.urls.items()},
            chain=list(providers.names), tenant_rate=tenant_rate, tenant_burst=tenant_burst, max_attempts_per_provider=2,
            first_token_timeout_ms=slo_ttft_ms * 2, slo_ttft_ms=slo_ttft_ms, breaker_window_s=breaker_window_s,
            breaker_min_samples=breaker_min_samples, breaker_cooldown_s=breaker_cooldown_s, breaker_probe_successes=2)

    # ---- gateway lifecycle -------------------------------------------------------------
    def _start_gateway(self):
        import uvicorn
        from llmgateway.app import create_app
        port = _free_port()
        server = uvicorn.Server(uvicorn.Config(create_app(self.cfg), host="127.0.0.1", port=port, log_level="error"))
        th = threading.Thread(target=server.run, daemon=True)
        th.start()
        url = f"http://127.0.0.1:{port}"
        assert _wait_health(url), "gateway did not start"
        return server, th, url

    # ---- the run -------------------------------------------------------------------------
    def run(self, fault: str | None, fault_arg=None, baseline_s: float = 10, fault_s: float = 30, recovery_s: float = 30) -> dict:
        server, th, gw = self._start_gateway()
        events: list[Event] = []
        records: list[dict] = []
        breaker_tl: list[dict] = []
        rate = {"value": self.rate}
        stop = threading.Event()
        t0 = time.monotonic()
        target = self.p.names[0]

        async def load():
            async with httpx.AsyncClient(base_url=gw, timeout=30, limits=httpx.Limits(max_connections=1000)) as c:
                tasks: list[asyncio.Task] = []

                async def one(sent_at: float):
                    body = {"model": "mock", "messages": [{"role": "user", "content": "ping"}], "max_tokens": self.max_tokens, "stream": False, "ignore_eos": True}
                    t = time.monotonic()
                    try:
                        r = await c.post("/v1/chat/completions", json=body, headers={"x-tenant": "user"})
                        ttft = float(r.headers.get("x-llmgateway-ttft-ms", (time.monotonic() - t) * 1000)) / 1000
                        ok, status = r.status_code == 200, r.status_code
                    except httpx.HTTPError as e:
                        ttft, ok, status = None, False, type(e).__name__
                    rel = sent_at - t0
                    if status != 429:
                        events.append(Event(t=rel, good=self.slo.good(ttft, ok)))
                    records.append({"t": rel, "ttft_s": ttft, "ok": ok, "status": status})

                nxt = time.monotonic()
                while not stop.is_set():
                    now = time.monotonic()
                    if now >= nxt:
                        tasks.append(asyncio.create_task(one(now)))
                        nxt += 1.0 / rate["value"]
                    else:
                        await asyncio.sleep(min(0.01, nxt - now))
                await asyncio.gather(*tasks, return_exceptions=True)

        def sample_breakers():
            while not stop.is_set():
                try:
                    m = httpx.get(f"{gw}/metrics", timeout=2).text
                    for prov, st in _BREAKER.findall(m):
                        breaker_tl.append({"t": time.monotonic() - t0, "provider": prov, "state": _STATE[int(st)]})
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)

        lt = threading.Thread(target=lambda: asyncio.run(load()), daemon=True)
        bt = threading.Thread(target=sample_breakers, daemon=True)
        lt.start(); bt.start()
        phases = []
        time.sleep(baseline_s); phases.append(("baseline", 0.0, time.monotonic() - t0))
        fault_rec = {"name": fault, "target": target, "arg": fault_arg, "start": time.monotonic() - t0}
        restarted_at = None
        if fault == "throttle":
            self.p.throttle(target, float(fault_arg or 2000))
        elif fault == "kill":
            self.p.kill(target)
        elif fault == "spike":
            rate["value"] = self.rate * float(fault_arg or 5)
        time.sleep(fault_s)
        fault_rec["end"] = time.monotonic() - t0
        phases.append(("fault", fault_rec["start"], fault_rec["end"]))
        if fault == "throttle":
            self.p.throttle(target, 0.0)
        elif fault == "kill":
            self.p.restart(target); restarted_at = time.monotonic() - t0
        elif fault == "spike":
            rate["value"] = self.rate
        time.sleep(recovery_s); phases.append(("recovery", fault_rec["end"], time.monotonic() - t0))
        stop.set(); lt.join(timeout=60)
        metrics = httpx.get(f"{gw}/metrics", timeout=5).text
        server.should_exit = True; th.join(timeout=5)
        return self._summarise(events, records, breaker_tl, metrics, phases, fault_rec, restarted_at)

    def _summarise(self, events, records, breaker_tl, metrics, phases, fault_rec, restarted_at) -> dict:
        events.sort(key=lambda e: e.t)
        series = burn_rate_series(events, self.slo, window_s=10, step_s=1)
        counters: dict[str, dict[str, int]] = {}
        for kind, label, v in _COUNTER.findall(metrics):
            counters.setdefault(kind, {})[label] = int(v)
        target = fault_rec["target"]
        opened = next((s["t"] for s in breaker_tl if s["provider"] == target and s["state"] == "open"), None)
        slow_before = sum(1 for r in records if fault_rec["start"] <= r["t"] <= (opened if opened is not None else 1e9)
                          and r["ttft_s"] is not None and r["ttft_s"] > self.slo.ttft_s)
        in_phase = lambda name: [r for r in records if next(p for p in phases if p[0] == name)[1] <= r["t"] < next(p for p in phases if p[0] == name)[2]]
        return {
            "fault": fault_rec, "phases": [p[0] for p in phases], "phase_bounds": phases,
            "requests": len(records), "errors": sum(1 for r in records if not r["ok"] and r["status"] != 429),
            "rate_limited": sum(1 for r in records if r["status"] == 429),
            "requests_in_baseline": len(in_phase("baseline")), "requests_in_fault": len(in_phase("fault")),
            "budget_consumed": budget_consumed(events, self.slo),
            "peak_burn_rate": max((s["burn_rate"] or 0) for s in series) if series else 0.0,
            "burn_series": series, "alerts": alerts_fired(events, self.slo, RULES),
            "recovery_s": recovery_time(events, self.slo, fault_end_s=fault_rec["end"], sustained_s=3.0) if fault_rec["name"] else None,
            "breaker_opened_at": opened, "slow_before_breaker": slow_before, "breaker_timeline": breaker_tl,
            "provider_restarted_at": restarted_at,
            "fallbacks": sum(counters.get("fallbacks", {}).values()), "retries": sum(counters.get("retries", {}).values()),
            "gateway_counters": counters, "events": [{"t": e.t, "good": e.good} for e in events],
            "records": records,
        }

    @staticmethod
    def to_json(result: dict) -> str:
        return json.dumps(result, indent=1, default=str)

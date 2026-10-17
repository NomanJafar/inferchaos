"""`inferchaos run`: baseline + three faults against mock providers behind llmgateway."""

from __future__ import annotations

import argparse
import sys

from inferchaos.experiment import Experiment, Providers
from inferchaos.report import write_results
from inferchaos.slo import SLO


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="inferchaos")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the fault suite against mock providers")
    r.add_argument("--out", default="results/mock")
    r.add_argument("--rate", type=float, default=6.0, help="requests per second of steady load")
    r.add_argument("--slo-ttft-ms", type=float, default=800)
    r.add_argument("--slo-target", type=float, default=0.99)
    r.add_argument("--baseline", type=float, default=20)
    r.add_argument("--fault", type=float, default=60)
    r.add_argument("--recovery", type=float, default=60)
    r.add_argument("--throttle-ms", type=float, default=2000)
    r.add_argument("--spike", type=float, default=8)
    r.add_argument("--only", default="baseline,throttle,kill,spike")
    a = p.parse_args(sys.argv[1:] if argv is None else argv)
    slo = SLO(target=a.slo_target, ttft_s=a.slo_ttft_ms / 1000)
    results = {}
    for name in a.only.split(","):
        prov = Providers(n=2, capacity=16, ttft_ms=40, itl_ms=2)
        prov.start()
        try:
            exp = Experiment(prov, slo, rate=a.rate, slo_ttft_ms=a.slo_ttft_ms, breaker_min_samples=10, breaker_window_s=15, breaker_cooldown_s=10,
                             tenant_rate=a.rate * 1.5, tenant_burst=a.rate * 3)
            fault = None if name == "baseline" else name
            arg = {"throttle": a.throttle_ms, "spike": a.spike}.get(name)
            results[name] = exp.run(fault, arg, a.baseline, a.fault, a.recovery)
            r_ = results[name]
            print(f"{name:9s} requests {r_['requests']:4d} errors {r_['errors']:3d} 429s {r_['rate_limited']:3d} budget {r_['budget_consumed']*100:5.0f}% "
                  f"peak burn {r_['peak_burn_rate']:5.0f}x opened {r_['breaker_opened_at']} recovery {r_['recovery_s']}", file=sys.stderr)
        finally:
            prov.stop()
    out = write_results(results, a.out)
    print(out["table"])

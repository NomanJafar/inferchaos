"""SLO arithmetic (CONCEPTS.md sections 1, 2, 4): good/bad events, burn rate over windows,
budget consumed, multi-window alerts, recovery time."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Event:
    t: float
    good: bool


@dataclass(frozen=True)
class SLO:
    target: float = 0.99          # fraction of good events required
    ttft_s: float = 0.8           # a request is good if it succeeded and its TTFT is within this

    @property
    def budget(self) -> float:
        return 1.0 - self.target

    def good(self, ttft_s: float | None, ok: bool) -> bool:
        return bool(ok) and ttft_s is not None and ttft_s <= self.ttft_s


def _bad_fraction(events: list[Event], start: float, end: float) -> float | None:
    window = [e for e in events if start < e.t <= end]
    if not window:
        return None
    return sum(1 for e in window if not e.good) / len(window)


def burn_rate_series(events: list[Event], slo: SLO, window_s: float, step_s: float) -> list[dict]:
    if not events:
        return []
    t0, t1 = events[0].t, events[-1].t
    out, t = [], t0 + step_s
    while t <= t1 + 1e-9:
        bf = _bad_fraction(events, t - window_s, t)
        out.append({"t": t, "bad_fraction": bf, "burn_rate": (bf / slo.budget) if bf is not None else None})
        t += step_s
    if not out or out[-1]["t"] < t1:          # always evaluate the window ending at the last event
        bf = _bad_fraction(events, t1 - window_s, t1)
        out.append({"t": t1, "bad_fraction": bf, "burn_rate": (bf / slo.budget) if bf is not None else None})
    return out


def budget_consumed(events: list[Event], slo: SLO) -> float:
    """Fraction of the error budget used by these events (1.0 = exactly the budget)."""
    if not events:
        return 0.0
    bad = sum(1 for e in events if not e.good)
    return bad / (len(events) * slo.budget)


def alerts_fired(events: list[Event], slo: SLO, rules: list[dict], step_s: float = 1.0) -> list[dict]:
    """rules: [{name, long_s, short_s, burn}]: fire when both windows exceed `burn`; clear when the long one drops below."""
    if not events:
        return []
    t0, t1 = events[0].t, events[-1].t
    fired: list[dict] = []
    active: dict[str, dict] = {}
    t = t0 + step_s
    while t <= t1 + 1e-9:
        for r in rules:
            lb, sb = _bad_fraction(events, t - r["long_s"], t), _bad_fraction(events, t - r["short_s"], t)
            long_br = lb / slo.budget if lb is not None else 0.0
            short_br = sb / slo.budget if sb is not None else 0.0
            if r["name"] not in active and long_br >= r["burn"] and short_br >= r["burn"]:
                active[r["name"]] = {"name": r["name"], "fired_at": t, "cleared_at": None, "peak_burn": long_br}
                fired.append(active[r["name"]])
            elif r["name"] in active:
                active[r["name"]]["peak_burn"] = max(active[r["name"]]["peak_burn"], long_br)
                if long_br < r["burn"]:
                    active[r["name"]]["cleared_at"] = t
                    del active[r["name"]]
        t += step_s
    return fired


def recovery_time(events: list[Event], slo: SLO, fault_end_s: float, sustained_s: float = 30.0) -> float | None:
    """Seconds from the end of the fault until `sustained_s` of events with no bad event."""
    after = [e for e in events if e.t >= fault_end_s]
    if not after:
        return None
    last_bad = fault_end_s
    for e in after:
        if not e.good:
            last_bad = e.t
        elif e.t - last_bad >= sustained_s:
            return e.t - fault_end_s
    return None

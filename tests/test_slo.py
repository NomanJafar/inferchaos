import pytest

from inferchaos.slo import (
    SLO,
    Event,
    alerts_fired,
    budget_consumed,
    burn_rate_series,
    recovery_time,
)


def _events(n_good, n_bad, t0=0.0, dt=0.1, bad_first=False):
    ev = []
    seq = ([False] * n_bad + [True] * n_good) if bad_first else ([True] * n_good + [False] * n_bad)
    for i, ok in enumerate(seq):
        ev.append(Event(t=t0 + i * dt, good=ok))
    return ev


def test_event_goodness_from_slo():
    slo = SLO(target=0.99, ttft_s=0.8)
    assert slo.good(ttft_s=0.5, ok=True) and not slo.good(ttft_s=1.2, ok=True) and not slo.good(ttft_s=0.1, ok=False)


def test_burn_rate_is_bad_fraction_over_budget():
    slo = SLO(target=0.99, ttft_s=0.8)
    ev = _events(80, 20)                                    # 20% bad over 10 s
    series = burn_rate_series(ev, slo, window_s=10, step_s=10)
    assert series[-1]["burn_rate"] == pytest.approx(0.20 / 0.01, rel=0.05)   # 20x


def test_budget_consumed_over_the_experiment():
    slo = SLO(target=0.99, ttft_s=0.8)
    ev = _events(990, 10)                                   # exactly the budget for these 1000 events
    assert budget_consumed(ev, slo) == pytest.approx(1.0)
    assert budget_consumed(_events(1000, 0), slo) == 0.0


def test_multi_window_alert_needs_both_windows_hot():
    slo = SLO(target=0.99, ttft_s=0.8)
    # 60 s of good, then 60 s with 50% bad (burn 50x), then 60 s good
    ev = _events(600, 0, t0=0) + [Event(t=60 + i * 0.1, good=(i % 2 == 0)) for i in range(600)] + _events(600, 0, t0=120)
    fired = alerts_fired(ev, slo, rules=[{"name": "page", "long_s": 60, "short_s": 5, "burn": 14.4}])
    assert fired and fired[0]["name"] == "page"
    # long window (60 s) must be hot: fires well after the fault starts, not at t=60
    assert 75 <= fired[0]["fired_at"] <= 100
    assert fired[0]["cleared_at"] is not None and fired[0]["cleared_at"] > 120


def test_recovery_time_is_from_fault_end_to_sustained_good():
    slo = SLO(target=0.99, ttft_s=0.8)
    ev = _events(100, 0, t0=0) + [Event(t=10 + i * 0.1, good=False) for i in range(100)] + \
         [Event(t=20 + i * 0.1, good=(i > 50)) for i in range(100)] + _events(300, 0, t0=30)
    r = recovery_time(ev, slo, fault_end_s=20.0, sustained_s=5.0)
    assert 5.0 <= r <= 11.0            # bad until ~25 s, then 5 s of good required
    assert recovery_time(_events(100, 0), slo, fault_end_s=0.0, sustained_s=2.0) == pytest.approx(2.0, abs=0.2)

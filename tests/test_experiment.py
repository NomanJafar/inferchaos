"""End-to-end: mock providers (subprocesses) behind llmgateway (thread), a steady load, one fault each."""

import pytest

from inferchaos.experiment import Experiment, Providers
from inferchaos.slo import SLO

SLO_ = SLO(target=0.99, ttft_s=0.8)


@pytest.fixture
def stack():
    p = Providers(n=2, capacity=16, ttft_ms=40, itl_ms=2)
    p.start()
    try:
        yield p
    finally:
        p.stop()


def test_baseline_burns_no_budget(stack):
    exp = Experiment(stack, slo=SLO_, rate=4.0, slo_ttft_ms=800, breaker_min_samples=10, breaker_window_s=10, breaker_cooldown_s=5)
    r = exp.run(fault=None, baseline_s=4, fault_s=4, recovery_s=4)
    assert r["requests"] > 30 and r["errors"] == 0
    assert r["budget_consumed"] < 0.5 and r["peak_burn_rate"] < 5
    assert r["phases"] == ["baseline", "fault", "recovery"]


def test_throttled_provider_trips_the_ttft_breaker_and_traffic_recovers(stack):
    exp = Experiment(stack, slo=SLO_, rate=6.0, slo_ttft_ms=800, breaker_min_samples=10, breaker_window_s=10, breaker_cooldown_s=4)
    r = exp.run(fault="throttle", fault_arg=2000, baseline_s=4, fault_s=12, recovery_s=10)
    assert r["fault"]["name"] == "throttle" and r["fault"]["target"] == stack.names[0]
    assert r["peak_burn_rate"] > 10                                   # slow requests burned budget
    assert r["breaker_opened_at"] is not None                         # the gateway noticed
    assert r["slow_before_breaker"] >= 1                              # ... but not instantly
    assert r["recovery_s"] is not None and r["recovery_s"] < 20
    assert any(s["state"] != "closed" for s in r["breaker_timeline"])


def test_killed_provider_falls_back_with_few_user_visible_errors(stack):
    exp = Experiment(stack, slo=SLO_, rate=6.0, slo_ttft_ms=800, breaker_min_samples=5, breaker_window_s=10, breaker_cooldown_s=4)
    r = exp.run(fault="kill", baseline_s=4, fault_s=8, recovery_s=10)
    assert r["fault"]["name"] == "kill"
    assert r["errors"] <= 3                                            # fallback absorbs almost everything
    assert r["fallbacks"] >= 1 and r["provider_restarted_at"] is not None
    assert r["recovery_s"] is not None


def test_traffic_spike_with_rate_limit_rejects_the_overflow_tenant(stack):
    exp = Experiment(stack, slo=SLO_, rate=3.0, slo_ttft_ms=800, tenant_rate=4.0, tenant_burst=4.0)
    r = exp.run(fault="spike", fault_arg=6, baseline_s=4, fault_s=6, recovery_s=4)
    assert r["fault"]["name"] == "spike" and r["rate_limited"] > 5
    assert r["requests_in_fault"] > r["requests_in_baseline"] * 3

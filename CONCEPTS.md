# Concepts: proving reliability by breaking things on purpose

`inferchaos` injects three faults into a serving stack (a throttled replica, a killed replica, a traffic spike), watches what users experience through the gateway, and scores it the way an SRE would: by how much of the error budget each fault burned and how long recovery took. The point is not to show that failures happen; it is to measure whether the mitigations built in projects 13 and 4 do what they claim, with numbers that would hold up in a post-mortem.

## 1. SLOs, error budgets and burn rate

An SLO states a target for a user-facing indicator over a window: "99.5% of requests return a first token within 1 s, measured over 30 days." The complement, 0.5%, is the **error budget**: the amount of badness the service is allowed per window. A 30-day budget of 0.5% at 10 requests/s is about 130,000 bad requests; spend it and the SLO is broken for the month.

**Burn rate** is how fast the budget is being consumed relative to the pace that would exactly exhaust it at the end of the window. A burn rate of 1 means the service will use precisely its budget over the window; 10 means it will be gone in a tenth of the window (3 days of a 30-day budget); 100 means hours. Burn rate is the metric that turns a latency incident into a number with a deadline attached:

```
burn_rate = (fraction of bad events in the last W) / (1 − SLO target)
```

A fault that makes 20% of requests bad against a 99.5% SLO burns at 40x: every minute of it costs 40 minutes of budget.

## 2. Multi-window alerting

Alerting on a single short window is noisy (one bad minute pages someone); on a single long window it is late (an outage must last an hour before the 1-hour average notices). The standard answer (Google's SRE Workbook) is **multi-window, multi-burn-rate**: page when the burn rate is high over *both* a long and a short window, so the condition is sustained and still current. Typical pairs:

| severity | long window | short window | burn rate | budget consumed by the time it fires |
|---|---|---|---|---|
| page | 1 h | 5 min | 14.4 | 2% of a 30-day budget |
| page | 6 h | 30 min | 6 | 5% |
| ticket | 3 days | 6 h | 1 | 10% |

This project implements the calculator (burn rate over arbitrary windows from a stream of good/bad events) and reports, for each fault, when each alert would have fired and when it would have cleared. The experiment's clock is minutes, not days, so the windows are scaled down; the arithmetic is the same.

## 3. The three faults and what they test

**Throttled replica (slow, not dead).** A GPU that is thermally throttled, or shared, or hit by a noisy neighbour, keeps answering but 3–10x slower. Health checks pass. This is the fault that breaks naive systems: nothing errors, every request through that replica is just late, and a round-robin balancer keeps sending it a fair share. It tests the gateway's *latency-based* degradation (project 13's TTFT breaker): does the breaker open on p95 TTFT, how long does it take, and how many requests were slow before it did? On a mock replica this is `extra_latency_ms` set at runtime; on the T4 it is approximated by a second process competing for the GPU.

**Killed replica.** The process dies mid-load: connections reset, in-flight streams break. It tests retries and the fallback chain (requests that had not started streaming should succeed on another provider), the breaker's error-rate trigger, and recovery when the replica returns (half-open probing). On the T4 this is literal: `kill -9` on the vLLM process during a sweep, then restart it.

**Traffic spike.** Arrival rate jumps 5–10x for a few minutes. Nothing is broken; capacity is simply exceeded. It tests rate limiting (which tenants get 429s), queueing behaviour and the autoscaler's response if one is in the loop. Its signature is rising TTFT and queue depth with no errors from the provider, and it is the fault most often misdiagnosed as a provider problem.

## 4. Recovery time and what "recovered" means

Recovery is measured from the moment the fault is removed to the moment the indicator is back inside the SLO for a sustained period (say, 30 s of good events). It has components that are worth separating: the time for the breaker to probe and close (cooldown + probes), the time to drain the backlog that accumulated during the fault, and, for the killed replica, the cold start itself. A long recovery after a short fault means the system amplifies failures; the numbers here say by how much.

## 5. What the gateway's metrics make visible

Every experiment reads two things at once: the user-side record (every request's TTFT, success, provider) from the load generator, and the gateway's own `/metrics` (breaker state per provider, retries, fallbacks, rate-limit rejections). Putting the breaker-state timeline next to the user TTFT timeline is the point of the exercise: it shows whether the mitigation fired *before* or *after* users felt the fault, and that gap is the thing to shorten.

## 6. What the experiment will show

Against three mock providers behind `llmgateway` with a steady open-loop load, with the SLO "TTFT ≤ 800 ms, success" at 99%:

1. **Baseline**: error budget burn ≈ 0; the alert thresholds never fire.
2. **Throttle** one provider to 5x TTFT for 3 minutes: burn rate over time, when the breaker opened, how many slow requests escaped before it did, recovery after the throttle lifts.
3. **Kill** a provider for 2 minutes: error-rate breaker, fallback success rate, requests lost (streams already started), recovery after restart including the half-open probes.
4. **Spike** to 8x load for 2 minutes: 429s per tenant, TTFT distribution, burn with and without rate limiting.
5. **On the T4**: one real replica behind the gateway, killed mid-load and restarted; measured recovery including vLLM's cold start.

Each fault gets a timeline plot (burn rate, breaker state, user TTFT) and one row in a table: budget burned, peak burn rate, alerts fired, recovery time.

## Further reading

- Beyer et al., *The Site Reliability Workbook* (2018), chapter 5, "Alerting on SLOs" (the multi-window table above is from there).
- Basiri et al., *Chaos Engineering* (IEEE Software, 2016) and the *Principles of Chaos Engineering*.
- Nygard, *Release It!*, on stability patterns and the ways slow dependencies hurt more than dead ones.

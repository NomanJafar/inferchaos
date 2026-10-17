# inferchaos

Chaos engineering for LLM inference: inject GPU throttling, replica kills and traffic spikes, then measure SLO burn and recovery.

Project 14 of 15 in [inference-infra-portfolio](https://github.com/NomanJafar/inference-infra-portfolio).

## What this builds

Inject GPU throttling, replica kills and traffic spikes into a serving stack and measure SLO burn and recovery.

## Why it matters

Reliability is proven under failure, not in demos.

## Status

Mock-provider suite done (results below); the T4 run that kills a real vLLM replica mid-load is in flight and will be added.

## What is in here

| Module | Purpose |
|---|---|
| `inferchaos.slo` | `SLO` (target + TTFT bound), good/bad events, burn-rate series over a window, budget consumed, multi-window alerts (page / ticket), recovery time |
| `inferchaos.experiment` | `Providers` (tokenbench mock servers as subprocesses: throttle at runtime, kill, restart), `Experiment` (llmgateway in a thread, steady open-loop load recording one SLO event per request, fault window, breaker-state sampling, summary) |
| `inferchaos.report` | Per-fault timeline (user TTFT, burn rate, breaker state, alerts) and the comparison table |
| `notebooks/kaggle_inferchaos.ipynb` | The same experiment with a real vLLM replica on a T4 as provider p0, killed with SIGKILL and restarted with its real cold start |

Ten tests; the four fault experiments run end to end (about 80 s) against live mock providers behind the real [llmgateway](https://github.com/NomanJafar/llmgateway).

## Usage

```bash
pip install "git+https://github.com/NomanJafar/inferchaos"
inferchaos run --out results/mock --rate 6 --baseline 20 --fault 60 --recovery 60
```

## Results: mock providers behind llmgateway (6 req/s, SLO: success and TTFT ≤ 800 ms at 99%)

Two providers in the chain (`p0`, `p1`), 16 concurrent requests each, 40 ms TTFT; gateway: first-token timeout 1.6 s, breaker on TTFT p95 / error rate over a 15 s window with 10 samples minimum and a 10 s cooldown; alert rules scaled to the experiment (page: 14.4x over 30 s and 5 s; ticket: 3x over 60 s and 10 s). Each run: 20 s baseline, 60 s fault on `p0`, 60 s recovery. "Budget consumed" is relative to the budget of the whole 140 s run, so 523% means the fault burned five runs' worth.

| fault | requests | errors | 429s | budget consumed | peak burn rate | alerts fired | breaker opened after | slow before breaker | fallbacks | recovery |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 840 | 0 | 0 | 0% of the run's budget | 0x | none | – | 0 | 0 | – |
| throttle | 841 | 0 | 0 | 523% of the run's budget | 67x | ticket @ 1s, page @ 4s | 7.1 s | 40 | 44 | 3.2 s |
| kill | 842 | 0 | 0 | 0% of the run's budget | 0x | none | 5.6 s | 0 | 36 | 3.2 s |
| spike | 3361 | 0 | 2324 | 0% of the run's budget | 0x | none | – | 0 | 0 | 3.0 s |

![faults](results/mock/faults.png)

### What the numbers say

1. **The slow provider is the dangerous one; the dead one is harmless.** Killing `p0` produced **zero** user-visible errors and burned **no** budget: every connection failed instantly, the gateway retried and fell back within a few hundred milliseconds, and the error-rate breaker opened 5.6 s in. Throttling `p0` to a 2 s TTFT burned 523% of the run's budget at a peak burn rate of 67x: 40 requests were slow before the TTFT breaker opened 7.1 s into the fault, because each of them had to wait the full 1.6 s first-token timeout before falling back, and until ten of them had done so the breaker had no grounds to act. Nygard's "slow dependencies hurt more than dead ones" is the measured difference between 0% and 523%.
2. **The breaker's probing is visible and costs a little each time.** In the throttle panel the breaker half-opens every 10 s cooldown, sends one probe, sees a 2 s TTFT and re-opens; each probe is one slow user request (the isolated dots at ~1.7 s). Fewer, more expensive probes versus faster recovery is the cooldown trade-off, and it shows as a cost per cycle here.
3. **Recovery was immediate in every case** (the 3 s figure is the floor of the metric: three seconds of sustained good events are required to declare recovery). Once the throttle lifted, the next probe succeeded and the breaker closed within one cooldown; once the killed provider was restarted, nothing changed for users because traffic was already on `p1`.
4. **Rate limiting turned the spike into 2,324 rejections and zero budget burn.** The admitted requests never left the 100 ms band. Whether a 429 is better than a slow answer is a product decision, but it is the decision that keeps the SLO, and the experiment shows the two outcomes do not mix: budget is burned by admitted-and-slow, not by rejected.
5. **The alerts fired fast because the burn was extreme** (ticket at 1 s, page at 4 s after the throttle began, against 30–60 s long windows): a 67x burn fills a long window's threshold in a fraction of the window. At a realistic 2–5x burn the long window would take minutes to fire, which is the point of the multi-window design.
6. **One gateway bug was found and fixed by this experiment:** the user-facing TTFT header reported the successful attempt's TTFT (40 ms on the fallback), hiding the 1.6 s the user actually waited on the throttled provider; the first throttle run therefore burned no budget at all. The header is now end-to-end and the per-attempt figure is separate. That is the kind of thing chaos testing is for.

## Layout

```
CONCEPTS.md     the theory behind the project, written before the code
src/inferchaos/   implementation
tests/          CPU-only tests, runnable on a laptop
notebooks/      GPU notebooks (Kaggle / Colab) that run the experiments and write results/
results/        measured numbers and plots
```

## Running

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

GPU experiments run from `notebooks/`; each notebook clones this repo, installs it and writes its outputs to `results/`.

## Hardware notes

Developed against free-tier GPUs (Kaggle and Colab T4, 16 GB). Where a T4 limits what can be measured (no FP8, Turing-era kernels), the README says so rather than papering over it.

## License

MIT

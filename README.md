# inferchaos

Chaos engineering for LLM inference: inject GPU throttling, replica kills and traffic spikes, then measure SLO burn and recovery.

Project 14 of 15 in [inference-infra-portfolio](https://github.com/NomanJafar/inference-infra-portfolio).

## What this builds

Inject GPU throttling, replica kills and traffic spikes into a serving stack and measure SLO burn and recovery.

## Why it matters

Reliability is proven under failure, not in demos.

## Status

Concept primer written (`CONCEPTS.md`). The fault injectors, burn-rate calculator and reports are next; one T4 run kills a real vLLM replica.

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

Run 3 (2026-10-17/18): the embedded-wheel route worked (first run of this notebook to get past the install), vLLM started in 161 s, the baseline minute ran, the kill fired, and the restart failed in 22 s:

```
ValueError: Free memory on device cuda:0 (1.64/14.56 GiB) on startup is less than desired GPU memory utilization (0.9, 13.11 GiB).
```

`startup_1.log` is that restart. The kill was `proc.kill()` on the `vllm serve` process: SIGKILL on the API server alone leaves its EngineCore child (a separate process that owns the CUDA context and the 12.9 GiB of weights and KV cache) alive. That is itself a finding about what "kill the replica" means: a process kill is not a node kill, and a supervisor that restarts on the same GPU must take the whole process tree down and wait for the driver to release the memory. servellm's `VllmServer` now starts the server in its own session and `kill()` signals the process group; the notebook waits for `nvidia-smi` to report under 1 GiB used before restarting, and records that release time next to the cold start.

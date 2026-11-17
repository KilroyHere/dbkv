# engine: Continuum fork (vLLM 0.10.2)

*Also here (Nov 16, §2j option E):* [E_task_eviction.md](E_task_eviction.md), the design of task-aware KV eviction for our vLLM 0.33; the code is a plugin in `harness/vllm_taskevict/`, not an engine fork.

- The Continuum code is github.com/Hanchenli/vllm-continuum (vLLM 0.10.2, Apache-2.0). It was located and built in `$SCRATCH/envs/continuum-env` (job 60826039).
- This direction makes no engine changes. Continuum is cited as a baseline only and was never run in experiments.
- The released code uses a fixed 2 s pin per tool (pin only if the tool's running-mean duration is under 2 s), not the paper's Eq. 1 timeout learned from each tool's past durations (PLAN §9a).

vLLM config (startup script)

Initial vLLM config (start_vllm_small.sh):
- `--model Qwen/Qwen3-30B-A3B-Instruct-2507`: required assignment model.
- `--host 0.0.0.0`: exposes the server to local Docker/port forwarding.
- `--port 8000`: assignment-standard vLLM endpoint.
- `--max-model-len 8192`: reduces KV-cache reservation from the model's full 262k context so the model fits on one H100; enough for the assignment's 1.5-3k token prompts and short SQL outputs.

The agent loop helped, but only modestly. It improved one question after revision, from 36.7% to 40.0%, then plateaued. So the architecture is not doing nothing, but the current verify/revise prompts are only weakly improving quality.

Baseline eval: 12/30 correct (40.0%). The first-pass SQL accuracy was 11/30 (36.7%). The verify/revise loop improved to 12/30 (40.0%) by iteration 2 and did not improve further by iteration 3. This indicates the loop adds a small amount of value, but the current verifier/reviser prompts are not yet strong enough to recover many failures.

Baseline observation
At 2 RPS, P95 was 4.39s but wall clock grew to 77s for a 60s run and max latency hit 70s, indicating queueing/backpressure. 
No errors occurred, so the bottleneck is serving throughput rather than correctness or HTTP stability.

The bottleneck does not look like KV cache exhaustion: KV usage stayed low. It also does not show a sustained scheduler queue: requests waiting stayed at 0. The issue is likely per-request work/agent fanout: each agent request triggers multiple sequential vLLM calls, so tail latency grows even at low external RPS.

Baseline load test at 2 RPS: achieved only 1.55 RPS over a 60s run, with P95 4.39s, P99 7.51s, and max latency 70.18s. Grafana showed low KV cache usage and no sustained waiting queue, but multiple concurrent running requests and latency spikes. Hypothesis: the agent's sequential LLM calls (`generate_sql` + `verify` + sometimes `revise`) dominate end-to-end latency rather than GPU KV capacity.

Saw high tail latency at 2 RPS with low KV usage and no sustained queue → hypothesized sequential agent LLM calls and excess output budget dominated latency → capped generate/revise to 192 tokens, verify to 80 tokens, and reduced max SQL attempts from 3 to 2 → P95 improved from 4.39s to 2.10s and max latency from 70.18s to 3.27s, with 0 errors.

Iteration 1: saw high tail latency at 2 RPS with low KV usage and no sustained queue. Hypothesis: sequential agent LLM calls and loose output limits dominated end-to-end latency. Changed `MAX_ITERATIONS` from 3 to 2 and capped LLM outputs (`generate_sql`/`revise` 192 tokens, `verify` 80 tokens). 

Result: at 2 RPS, P95 improved from 4.39s to 2.10s, P99 from 7.51s to 2.46s, max latency from 70.18s to 3.27s, and achieved RPS improved from 1.55 to 1.94 with zero errors.

At 5 RPS after token/loop tuning, P95 regressed to 8.40s, achieved RPS was only 2.50, and max latency reached 51.84s. The system saturates between 2 and 5 RPS, so the 10 RPS / P95<5s SLO is not reachable with the current multi-call agent architecture and single H100 serving config.

At 5 RPS after token/loop tuning, the agent produced 298/300 successful responses but achieved only 2.50 RPS over a 120s wall-clock drain. P95 latency was 8.40s and max latency was 51.84s. The two client errors were server disconnects under load, suggesting overload rather than deterministic request failures.










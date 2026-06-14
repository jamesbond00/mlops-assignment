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







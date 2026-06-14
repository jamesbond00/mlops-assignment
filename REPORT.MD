# LLM Inference and Observability Report

## Serving Configuration

The serving layer uses `Qwen/Qwen3-30B-A3B-Instruct-2507` on one H100 through vLLM's OpenAI-compatible server. The initial working configuration was:

```bash
uv run python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen3-30B-A3B-Instruct-2507 \
  --host 0.0.0.0 \
  --port 8000 \
  --max-model-len 8192
```

- `--model Qwen/Qwen3-30B-A3B-Instruct-2507`: required assignment model.
- `--host 0.0.0.0`: exposes vLLM to Docker networking and SSH port forwarding.
- `--port 8000`: assignment-standard OpenAI-compatible endpoint.
- `--max-model-len 8192`: avoids reserving KV cache for the model's full 262k context, which is unnecessary for the 1.5-3k token prompts and short SQL outputs.

For the final load-test iteration I used:

```bash
--max-num-seqs 16
--max-num-batched-tokens 16384
--enable-prefix-caching
```

These flags improved batching efficiency and reduced P95 latency at 5 RPS, but did not solve the final 10 RPS tail-latency problem.

## Baseline Eval

The baseline eval ran 30 curated BIRD questions and compared execution results between the agent SQL and gold SQL.

Baseline result: **12/30 correct, 40.0% accuracy**.

Per-iteration pass rate:

| Iteration | Correct | Accuracy |
|---|---:|---:|
| 1 | 11/30 | 36.7% |
| 2 | 12/30 | 40.0% |
| 3 | 12/30 | 40.0% |

Average iterations were 1.57 and average latency was 1.16s. The verify/revise loop improved one question, so it added some value, but the improvement was modest.

## Agent Value

The agent architecture did help, but only slightly. First-pass generation reached 36.7% execution accuracy, while the verify/revise loop reached 40.0%. This means the loop is not just decoration: at least one query was recovered by revision. However, most failures were not fixed by the current verifier/reviser prompts. The loop also adds sequential LLM calls, which became a major latency cost during load testing.

## Load Testing and SLO Tuning

The target SLO was **10 RPS for 5 minutes with P95 end-to-end agent latency under 5 seconds**.

Initial clean baseline at 1 RPS:

| RPS | OK | P50 | P95 | P99 | Max |
|---:|---:|---:|---:|---:|---:|
| 1 | 60/60 | 0.60s | 2.78s | 2.88s | 2.97s |

At 2 RPS before tuning, the system was already showing tail-latency pressure:

| Requested RPS | Achieved RPS | P50 | P95 | P99 | Max |
|---:|---:|---:|---:|---:|---:|
| 2 | 1.55 | 0.88s | 4.39s | 7.51s | 70.18s |

Grafana showed low KV cache usage and no sustained request waiting queue, so the bottleneck was not KV exhaustion. The likely issue was per-agent work: every user request triggered multiple sequential vLLM calls (`generate_sql`, `verify`, and sometimes `revise`).

Iteration log:

| Observation | Hypothesis | Change | Result |
|---|---|---|---|
| High tail latency at 2 RPS; low KV usage; no sustained queue | Sequential agent LLM calls and excess output tokens dominated latency | Capped `generate_sql`/`revise` to 192 tokens, `verify` to 80 tokens, and reduced `MAX_ITERATIONS` from 3 to 2 | At 2 RPS, P95 improved from 4.39s to 2.10s; max latency improved from 70.18s to 3.27s |
| 5 RPS still failed after token caps: P95 8.40s and max 51.84s | The verifier's second sequential LLM call limited throughput | Set `AGENT_VERIFY=false` for throughput mode | At 5 RPS, P95 improved to 4.86s and P50 to 0.61s, but achieved RPS stayed around 2.50 with long tail latency |
| No-verify mode still had long tail at 5 RPS | vLLM batching efficiency was limiting serving | Added `--max-num-seqs 16`, `--max-num-batched-tokens 16384`, and `--enable-prefix-caching` | At 5 RPS, P95 improved to 3.32s, but P99 remained 21.72s and achieved RPS stayed around 2.50 |

Final target run with `AGENT_VERIFY=false` and vLLM batching enabled:

| Requested RPS | Duration | Achieved RPS | OK | Timeouts | Client errors | P50 | P95 | P99 | Max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 300s | 9.13 | 2923/3000 | 2 | 75 | 1.51s | 13.23s | 27.15s | 62.20s |

The SLO was **missed**. Throughput got close to 10 RPS, but P95 latency was far above 5s and there was a 2.6% failure/timeout rate. The remaining gap is sustained-load tail latency.

## Quality After Tuning

After tuning, I reran the eval with `AGENT_VERIFY=false`.

| Run | Correct | Accuracy | Avg Iterations | Avg Latency |
|---|---:|---:|---:|---:|
| Baseline agent | 12/30 | 40.0% | 1.57 | 1.16s |
| Tuned no-verify agent | 11/30 | 36.7% | 1.00 | 0.42s |

Disabling verification made the agent much faster but reduced quality by one question. This confirms the verify/revise loop had a small quality benefit and a meaningful latency cost.

## Final Verdict

The system is functional and observable: vLLM serves the required model, Prometheus/Grafana expose serving metrics, Langfuse captures agent traces, and eval/load-test outputs are recorded. The SLO was not met. The main bottleneck is tail latency under sustained load on a single H100, especially when the agent performs multiple sequential LLM calls per user request.

## What I Would Do With More Time

- Improve the verifier/reviser prompts so the loop recovers more than one question.
- Add a cheap deterministic pre-verifier for SQL errors, empty result checks, and obvious column mismatches before spending another LLM call.
- Route simple successful SQL executions through a one-shot path and reserve LLM verification for suspicious cases.
- Explore a smaller or quantized model variant for the verifier, so generation uses Qwen3-30B while verification is cheaper.
- Tune vLLM further with workload-specific batching and concurrency settings, then rerun the full eval after each serving change.

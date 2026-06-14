vLLM config (startup script)

Initial vLLM config (start_vllm_small.sh):
- `--model Qwen/Qwen3-30B-A3B-Instruct-2507`: required assignment model.
- `--host 0.0.0.0`: exposes the server to local Docker/port forwarding.
- `--port 8000`: assignment-standard vLLM endpoint.
- `--max-model-len 8192`: reduces KV-cache reservation from the model's full 262k context so the model fits on one H100; enough for the assignment's 1.5-3k token prompts and short SQL outputs.




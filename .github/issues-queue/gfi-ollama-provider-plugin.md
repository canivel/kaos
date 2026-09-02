# Plugin: Ollama provider (`kaos-plugin-ollama`) via raw httpx

Labels: good first issue, enhancement · Priority: P2

KAOS routes to five providers today (anthropic, openai-compatible, claude_code, agent_sdk,
local vLLM). Ollama is the most common way people run local models and it is *not* fully
OpenAI-compatible for tool calls. This is a self-contained plugin, no core changes.

**What to build**

- Start from `contrib/plugin-template/`; publish as `kaos-plugin-ollama`.
- `register(reg)` → `reg.add_provider("ollama", make_ollama_provider)`.
- Provider talks to `http://localhost:11434/api/chat` with **raw `httpx`** (no `openai`
  SDK, no `litellm` — repo rules), maps KAOS messages/tools to Ollama's `messages` /
  `tools` fields, returns `LLMResponse` (see `kaos/router/providers.py`).
- Handle `stream=false`, a configurable `base_url`, and a clear error when the daemon
  isn't running.

**Done when**

- `kaos.yaml` with `provider: ollama, model_id: llama3.2` runs `kaos run -n t "say hi"`.
- Tests mock `httpx` (no daemon needed in CI) and cover one tool call round-trip.

Reported by AI agent

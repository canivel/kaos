# kaos-plugin-codex

A KAOS model provider that drives the **OpenAI Codex CLI** (`codex exec`) as a
subprocess. Authentication is whatever `codex login` set up — for most users a
ChatGPT subscription — so **no `OPENAI_API_KEY` is needed**. This is the Codex
counterpart of the built-in `claude_code` provider.

```yaml
# kaos.yaml
models:
  codex:
    provider: codex
    model_id: gpt-6-astra        # any id `codex exec -m` accepts
    max_context: 400000
    use_for: [complex, critical]
    timeout: 1800                # wall seconds per call
    idle_timeout: 300            # no-new-bytes seconds before ProposerStalled
```

Optional keys (all read from the model block): `sandbox` (`read-only` default,
`workspace-write`, `danger-full-access`), `cwd` (passed as `codex exec -C`),
`reasoning_effort` (`low|medium|high|xhigh`, sent as
`-c model_reasoning_effort=...`), `codex_executable` (else `$CODEX_EXECUTABLE`
or `codex` on PATH), `extra_args` (list appended verbatim).

The conversation (system/user/assistant/tool messages + the KAOS `<tool_call>`
protocol) is serialized with `kaos.router.providers.serialize_conversation`
and piped on stdin; the final assistant message is read back from
`--output-last-message` so Codex's own transcript chatter never pollutes the
parse. Sessions are `--ephemeral` (nothing written under `~/.codex/sessions`).

Install next to KAOS:

```bash
uv tool install --python 3.12 'kaos-harness[all]' --with-editable contrib/kaos-plugin-codex
kaos plugins            # -> codex (provider)
kaos doctor proposer    # smoke-tests every configured provider
```

Requires kaos-harness >= 2.1.2 (`GEPARouter` resolves plugin providers from
`kaos.yaml`); on older cores inject manually:
`router.clients["codex"] = make_codex_provider(model_id="gpt-6-astra")`.

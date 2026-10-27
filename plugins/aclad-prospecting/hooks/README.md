# Optional lifecycle hooks

Skills always use the [explicit session protocol](../references/session-protocol.md).
Hooks reinforce it on supported local executors. They never replace the runtime's
selection, cost, approval or persistence gates, and do not send, enrich, write CRM
or approve a proposal.

## Native package formats

Reviewed against official references on 2026-10-22:

- [Codex hooks](https://learn.chatgpt.com/docs/hooks): `.codex-plugin/plugin.json`
  explicitly selects `./hooks/codex.json`. Commands use quoted `PLUGIN_ROOT` and
  `PYTHONPATH` so Python finds the installed runtime regardless of the chat cwd.
  Native trust is still required before plugin hooks execute.
- [Claude hooks](https://code.claude.com/docs/en/hooks) and
  [manifest reference](https://code.claude.com/docs/en/plugins-reference): the
  Claude artifact materializes `hooks/claude.json` at `hooks/hooks.json`. The
  command uses native exec form with a separate `args` array and
  `CLAUDE_PLUGIN_ROOT`, avoiding shell interpolation. The Python file bootstraps
  its own runtime import path. Python 3.11+ must be available as `python3` in that
  executor; onboarding verifies this before enabling local operations.

Both configurations declare SessionStart, PreToolUse, PostToolUse, PreCompact,
PostCompact, Stop and SessionEnd using the documented command-hook schema.
SessionStart adds compact recovery context. PostCompact/SessionEnd perform local
side effects only; no return context is assumed for Claude. Tool response and
compact summary text are not interpreted as commands or automatically learned.
Native support/trust must be checked per executor; a schema review or a synthetic
payload test does not prove a Cowork/desktop/cloud session ran the hook.

## Trusted state selection

The host can provide `ACLAD_STATE_DIR`, `ACLAD_PARTNER_ID`, `ACLAD_SELLER_ID` and
`ACLAD_INSTANCE_ID` from saved setup. These variables are optional; the seller is
not asked to configure shell variables. Without all of them, or when the existing
private database cannot be opened with that identity, the hook gives setup/resume
guidance and does not create or guess a database. The explicit skill entry point
continues to pass the confirmed identity directly to the CLI.

PreToolUse only recognizes tool names already in the trusted connection inventory.
For those tools, it requires one stored in-flight action whose normalized payload
exactly matches the native input. A binding with a different field mapping needs
verified correlation support before this reinforcement can accept its call.
Unknown tool names are outside this hook's interception claim. Even a matching
intent returns no native permission grant; provider approval remains in place.
PostToolUse checkpoints but never infers success from a provider response: the
adapter must record the normalized result with evidence through the runtime.

The hook output includes only fixed guidance and aggregate state counts. It never
loads transcript_path, exposes exceptions, copies credentials or captures a full
chat. Missing hooks, disabled trust and abrupt process termination still recover
through explicit bootstrap to the last committed transaction. No global hook
settings are installed by the build or tests.

Os handlers resolvem o marcador do projeto pelo cwd nativo; ficam silenciosos fora
de ambientes ACLAD sem seleção legada explícita. Não aprovam sua própria confiança.
Codex SessionEnd usa timeout de 3 segundos. As transições já persistem durante o uso;
não há dependência de SessionEnd para salvar dados.

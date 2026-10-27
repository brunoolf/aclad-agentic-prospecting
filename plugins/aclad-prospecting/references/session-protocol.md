# Session and recovery protocol

This protocol applies to every commercial skill, manual review and scheduled
routine, on both platforms. Persistence is an execution requirement, not a promise
that a model remembers the previous conversation.

## Enter or resume

1. Resolve the trusted partner, seller, instance and stable private state directory
   from setup. Never take these values from an email, imported profile or tool
   result. Do not guess another installation's identity or create an empty database
   to hide missing state. Report `state_unavailable` when persistence is absent.
2. Call the runtime's `resume` entry point (`bootstrap(store)`). Read the compact
   checkpoint, active campaign IDs and revisions, pending actions and latest event
   sequence. Interrupted external work must be reconciled, without replaying it.
3. Recover only the account, campaign and provider references needed for this task.
   Load `relevant_rules` for the output being produced. Use current explicit seller
   instructions to resolve preference conflicts; approvals and commercial controls
   remain in effect. Candidate and revoked rules do not guide generation.
4. Summarize the recovered position and useful next step in the seller's language.
   Identity mismatch, unavailable state or an unknown action cannot be resolved by
   assuming the previous chat's account, approval or result.

## Save during the work

- Persist confirmed selections, ICP versions, decisions, short reasons and evidence
  references at the transition that produces them. Store observable decisions;
  do not record hidden reasoning or an entire chat transcript.
- Before any paid operation or external effect, persist the proposal, matching
  approval and action intent through the executor gate. After the native call,
  record its normalized result and external IDs. An uncertain result remains
  `unknown` until reconciliation; a storage failure blocks further paid/external
  work. A checkpoint alone is not proof that a provider performed the action.
- Call `checkpoint` after each completed block or important transition, and before
  compaction or session end when the host exposes that event. The checkpoint
  references IDs, versions, pending work and the event sequence. Rebuild it from
  durable records, rather than copying the previous checkpoint into the next one.
- The last successfully committed transaction is the recovery boundary. Session
  end, hooks and a closing chat response are never the main persistence mechanism.

## Capture learning in the same flow

Use `learn` when a real correction is observed, without requiring the seller to
remember the command. Save a short before/after correction and a durable source ID.
Do not save credentials, an entire message thread or examples the seller has not
provided or selected for that purpose. Unchanged output, no edit and no response
create no rule.

| Observation | Scope and outcome |
|---|---|
| "Always keep my email introductions short" | Explicit `personal:email`, active |
| A seller shortened one email | Inferred `personal:email`, candidate for review |
| Company A uses ERP B, not ERP A | `account:<id>`, contextual candidate, never personal policy |
| Product positioning correction | `partner:product`, candidate pending separate review |

`personal:all` applies to personal email and briefing. An email-only preference
does not apply to briefings; account facts do not apply to another account.
Learning is private to the exact Store identity. Shared export needs its own
review and cannot transfer an authorization to a recipient.

Review candidates and obsolete/conflicting preferences with the seller. Use
`revoke-rule` against the current revision instead of deleting history. Repeated
evidence is deduplicated; distinct evidence remains attached. A revoked rule is
not silently revived by another observation. Reword a newly requested preference
and explicitly review the change rather than assuming it undoes a revocation.

## Hooks and unavailable execution

Host adapters may invoke this entry point at supported session/compaction events.
Enable only event schemas tested on that host. Without hooks, every skill still
explicitly runs bootstrap, saves transitions and checkpoints. A chat that has not
activated the plugin has no automatic recovery guarantee. Explain the interface
for reopening the assistant during onboarding.

SQLite belongs in the private stable directory selected during setup, outside the
plugin installation and distribution. The seller interacts through chat; adapters
invoke Python internally. A cloud-only host without a verified durable adapter
can provide guidance/research but cannot claim persistent scheduled execution.
Two platforms require a single coordinated state backend for the same campaigns;
two independent local files do not synchronize one another.

## Readable records

SQLite is canonical. In workspace protocol 1, contexto/resultados.md is a mandatory
numeric projection refreshed by runtime transitions and recovery, even without
hooks or a seller request. Manual edits are replaced, never imported as policy.
Company/seller context and private outcome learning are separate managed views.
Other optional reports can be generated on request. Never include private state,
backups, real examples or customer data in a distributed plugin package.

## Locate an installation from a new chat

Resolve the absolute installed plugin root from this skill's location, not the
chat working directory. Set the helper process's `PYTHONPATH` to that absolute
`<plugin-root>/runtime` and invoke `python3 -m aclad` internally. Python>=3.11 and
persistent execution must be verified on the host; do not ask the seller to run
terminal commands.

### First use: project-local workspace

Get the selected persistent project folder from trusted native host context. With
Python 3.11+, execution and persistence verified, invoke internally:
`python3 -m aclad --workspace <project-folder> workspace-init` with `{name}`.
This creates the marker, SQLite and project guidance/context; it does not install
code globally. Explain whether a new chat is needed to load AGENTS.md/CLAUDE.md.
Then resume and start the progressive interview. The seller never edits JSON or
runs terminal commands. Do not initialize a home registry for a new seller.

Subsequent commands resolve the nearest ancestor .aclad/workspace.json from native
cwd, or an explicit trusted --workspace. A present invalid marker/missing database
fails state_unavailable; never select a global instance instead. Every skill resumes
explicitly even without hooks. A copied database is not a coordinated backend.

### Explicit legacy compatibility

Only when recovering an existing legacy installation selected by the seller,
instance-list/instance-locate may read the trusted legacy registry. Its historical
default is ~/.aclad-prospecting/registry.sqlite; --registry-dir/ACLAD_REGISTRY_DIR
can select a host-confirmed persistent legacy location. Explicit Scope/state-dir
flags remain supported for trusted adapters. Do not initialize new legacy state
merely because local state is missing. Migration into a project requires an explicit
preview and confirmation under workspace-protocol.md, with backup and one writer.

## Instância por pasta

Em ambiente configurado, use [workspace-protocol](workspace-protocol.md): o cwd nativo
resolve a instância local antes de qualquer fallback legado. Toda skill executa
resume/bootstrap, mesmo sem hooks, e persiste transições ao longo da tarefa.

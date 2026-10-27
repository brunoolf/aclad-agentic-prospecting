---
name: save-to-crm
description: Propose reviewed accounts, contacts, relationships and owner assignment, then apply each approved CRM change with reconciliation.
---
# Save to CRM

## Contratos internos antes de executar

O vendedor conversa no próprio idioma; não lhe peça JSON, Python, IDs ou nomes de
campos. Resolva a raiz absoluta do plugin como `../..` a partir deste SKILL.md.
Para o operador: leia [as receitas](../../references/operator-recipes.md). Use
`python3 -m aclad help`, `schema COMMAND` e `examples COMMAND` com PYTHONPATH
apontando para o runtime instalado antes de chamar um comando ainda não conhecido.
Essas consultas não exigem stdin, pasta configurada, banco ou conexão. Os contratos
vêm das assinaturas atuais; exemplos são sintéticos e não comprovam autorização.
Não adivinhe campos, nomes de funções Python ou referências inexistentes. Use os
links desta skill e [os contratos](../../references/runtime-contracts.md).

Resume `../../references/session-protocol.md`. Recheck CRM identity, owner, history,
active opportunity and contact restrictions before writing. Own nurturing can
be eligible; another owner is not reassigned silently. Resolve the requested
assignee to an observed CRM user, asking who should own the records.

Use crm-propose with field-by-field before/after, provenance and relationships.
Show created/updated records, exact owner and per-item changes. The seller may
remove items. Approval is for that version only; changing it requires new review.

After approval, use crm-item-prepare for one change_id with current provider
revision and preflight. Execute the native intent and crm-item-record the result.
Apply accounts before linked contacts. Do not treat a batch as an atomic transaction.
Show succeeded/failed/unknown outcomes separately. Timeout is not a safe retry;
use crm-reconcile to check IDs/provider state before any repetition. Never create
a new record merely because the response to its first creation was lost.

The intent includes a stable `operation_id`. Map it to a provider-supported
correlation/idempotency field only after verifying that mapping. A second proposal
cannot repeat an overlapping unknown/in-flight operation. If creation cannot be
uniquely correlated, leave it unresolved and ask for reconciliation evidence.

`crm-reconcile` requires one complete observation for the local item, evidence,
actual `fields`, `links`, `owner_ref` and full `external_ref`. Updates must match
the approved target/changes and show a changed `external_revision`; creates need
the matching `operation_id` as well. An existing unchanged object is not success.
Only correlated provider evidence of `status=not_applied` and
`definitive_no_effect=true` can settle an uncertain action as failed before retry.

---
name: find-accounts
description: Build a reviewable account list from a selected ICP, CRM nurturing or connected data sources, before enrichment.
---
# Find accounts

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

Resume with `../../references/session-protocol.md`. If no approved ICP exists, use
`build-icp`; choose its version and campaign, and explain filters and exclusions.
Use the partner CRM (including eligible owned nurturing) and/or sources the seller
selected. Confirm paid/unknown search cost and a bounded result count before querying.

Create the durable campaign with `campaign-create` before binding the approved
ICP through `icp-bind`. Prepare search with `prospecting-propose`, then use the
common `prepare-action` → native call → `record-result` bridge. Ingest only the
candidates actually present in that succeeded action using `candidates-record`
with its action ID as `evidence_id`, kind `account`, and full external references.
Do not seed operational records from free-form chat or use a report as state.
Refreshing an existing candidate preserves restrictions and enriched/CRM state;
an external-identity conflict requires reconciliation, not a local-ID overwrite.

Show candidate identity, source, known firmographics, fit, owner and relevant history.
Use only available data for this list; do not enrich the list to make ranking easier.
Resolve uncertain identity and CRM eligibility through `check-crm`. Ask which
accounts the seller wants to work, then persist with `accounts-select`.
Only selected accounts can enter `companies.enrich` and deeper research.
Keep source gaps explicit and respect unsupported filters in each connector.

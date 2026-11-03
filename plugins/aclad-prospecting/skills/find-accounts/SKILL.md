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

Resume with `../../references/session-protocol.md` and inspect `setup-status`.
Finish the current onboarding block before operational discovery. Recover the
chosen campaign with `campaign-context`; if no approved ICP exists, use
`build-icp`, name it and obtain approval of its exact version before binding.

**Account discovery is through the connected prospecting provider or eligible
CRM nurturing only. Never use web search, social sites or inferred company lists
as fallback discovery.** A missing/blocked Lusha, Apollo, ZoomInfo or other chosen
provider is a connection task: help connect an allowed source and keep discovery
blocked. Web tools are for contextual research after a company is mapped, not
candidate sourcing. Confirm paid/unknown search cost and bounded count first.

Create the durable campaign with `campaign-create` before binding the approved
ICP through `icp-bind`. Prepare search with `prospecting-propose`. Inspect the
provider's actual schema and use `proposal-bind-native` to map the reviewed
filters and limits.max_items to its real arguments before approval. Approve the
returned revision/digest, not the old proposal. A first operation carrying
operation_validation needs explicit approval even when free. Use `prepare-action`,
call the exact native tool with payload.native_request.input, then `record-result`. Ingest only the
candidates actually present in that succeeded action using `candidates-record`
with its action ID as `evidence_id`, kind `account`, and full external references.
Do not seed operational records from free-form chat or use a report as state.
Refreshing an existing candidate preserves restrictions and enriched/CRM state;
an external-identity conflict requires reconciliation, not a local-ID overwrite.

Show the initial seller-facing table with **company name and website only**.
Persist provenance, source identity, filters, existing firmographics and CRM
eligibility privately; explain coverage/gaps without crowding the table. A source
reference is not a second website. Do not enrich this list to improve ranking.
Resolve uncertain identity and CRM eligibility through `check-crm`. Ask which
accounts the seller wants to work, then persist with `accounts-select`.
Only selected accounts can enter `companies.enrich` and deeper research.
Keep source gaps explicit and respect unsupported filters in each connector.

After selection, recover `campaign-context`, save the exact chosen IDs and present
the next stage: company enrichment/research. Do not jump from a request for
“contacts” to all candidates; first settle account selection and the required
company context. All source actions use the persisted runtime bridge, including
when native hooks are unavailable.

---
name: check-crm
description: Read account ownership and history, check portfolio eligibility and distinguish owned nurturing from another seller's active work.
---
# Check CRM

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

Read `../../references/session-protocol.md` and resume the private runtime first.
Discover the CRM tools exposed in this chat; configuration alone is not proof of access.
Use read-only lookup by CRM ID, tax ID, domain, then legal/trade name. Names and
shared group domains require review; a failed lookup never means an account is free.

Normalize account identity, owner reference, last activity, open opportunity,
blocking requests and CRM access status. Use `account-match` and `account-eligibility`
with the current seller's complete CRM identity. Report eligible, blocked or needs
review with reasons. An account belonging to this seller can be eligible for
nurturing; another owner is never reassigned silently. Do not invent an inactivity
interval. Preserve CRM history for the briefing. Revalidate before writing/sending.

Do not write to CRM in this skill. Save the read result and decision in private
state with provenance; never store credentials or return another seller's state.

Use a `crm.read` proposal and the common execution bridge to save the real lookup
with `record-result`. A complete normalized result contains `observations`, each
with the matching local `account_id`, and the verified ownership/history fields.
Call `account-check` with campaign/account IDs, that exact observation, the saved
read action ID as `evidence_id`, the current full `seller_ref` and reviewed rules.
This persists eligibility used by `accounts-select`; `account-eligibility` alone
is a pure calculation and cannot replace the saved check. Partial/failed lookup
does not establish that a company is available.

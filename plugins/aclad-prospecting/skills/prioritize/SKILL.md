---
name: prioritize
description: Rank candidate accounts against the campaign's approved ICP snapshot using available data, explain gaps and eligibility, and let the seller select accounts before paid enrichment.
---

# Prioritize candidate accounts

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

Run the [session protocol](../../references/session-protocol.md), recover the
campaign and its `icp_id`, `icp_revision` and `icp_snapshot`. If it has no approved
binding, use `build-icp` and obtain the seller's choice first. Never substitute the
latest proposed ICP for the campaign's approved version.

Use the candidate list and existing CRM/source data. Do not perform even "cheap"
enrichment before selection to obtain a score. Search itself may consume credits;
use the selected connection's verified cost/authorization gate.

Evaluate in this order:

1. Commercial exclusions, ownership, opportunity status and contact blocks. An
   inherited free-text exclusion needs an explicit interpretation; uncertain
   eligibility is a review item. Personal targeting cannot erase partner rules.
2. Fit against the approved criteria: country, state, industry, subindustry,
   employees, solutions and comparable annual revenue. Explain matches and missing
   fields. Revenue thresholds need the same currency/year or a reviewed conversion,
   never a comparison with deal value.
3. Timing supported by evidence and history. Distinguish facts from a hypothesis
   of need. Nurturing in the seller's own portfolio can be eligible; a different
   owner requires permission/attribution resolution, not silent reassignment.
4. Available professional-contact information, without revealing emails or paying
   for contact enrichment during prioritization.

Present an ordered table with one concrete reason and any data/eligibility gaps
per account. Explain meaningful differences without a fabricated confidence score.
State the ICP version and actual coverage. Invite the seller to select the accounts
and present the known cost/limit for the next enrichment step. Only selected and
properly authorized IDs can advance. Save selection and checkpoint immediately.

---
name: batch
description: Coordinate a list through account selection, company enrichment, approved roles, selected contacts and reviewed CRM/outreach actions.
---
# Batch

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

Inspect `setup-status` and `campaign-context` before starting operational work.
Resume the campaign using `../../references/session-protocol.md`. Deduplicate by reliable
identity; ambiguous names or group domains need review. Check CRM access, ownership,
activity and opportunities, including the seller's own eligible nurturing accounts.

Show the initial account table with name and website only, using the pinned ICP
and existing source data. Discovery uses CRM/prospecting tools; no web fallback
for companies, people or emails. Persist the seller's account
selection before company enrichment. Explain costs/limits and use gated proposals
for paid operations. Deep research covers only the selected scope.

After research: briefing → confirm roles → search candidates without revealing
email → seller selects people → reveal selected emails → propose CRM fields,
relationships and owner → approval → apply and reconcile → plan outreach.
Do not skip these stages or use approval of one stage for another. On partial
failure show outcomes by item; unknown effects require reconciliation before retry.
Every decision and next action is saved in private state, not just in this chat.

After the reviewed CRM stage, create native drafts through `outreach`, show their
links for review, obtain separate send approval and record delivery. The campaign
keeps one fixed objective and approved ICP revision across list, selection,
enrichment, contacts, CRM, drafts, sends, replies, follow-ups and meeting/discard.
Do not restart the campaign merely because a different chat is opened.

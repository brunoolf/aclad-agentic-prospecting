---
name: find-contacts
description: Suggest and confirm business roles, then search candidate people without revealing paid contact data.
---
# Find contacts

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

Resume `../../references/session-protocol.md`; work only on selected accounts. Retrieve
reviewed industry/persona rules and explain why each proposed role is relevant.
Confirm titles, seniority and bounded quantity, then save with `roles-confirm`.
Inspect the connector for separate `people.search` and `people.reveal_email`
capabilities. If inseparable, explain before any credit-consuming call.

Prepare `prospecting-propose` for people.search with selected account IDs and cost
limits. Use the approved intent/native tool/result protocol. Normalize and persist
candidates with `candidates-record`; evidence must reference the completed search.
Show name, company, role, source and data availability. Let the seller select
people, then persist `contacts-select`. Do not reveal email in this stage. Data
returned incidentally does not authorize its use or select that person.

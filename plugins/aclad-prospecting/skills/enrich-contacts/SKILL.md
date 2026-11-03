---
name: enrich-contacts
description: Reveal professional email only for people explicitly selected by the seller, with bounded cost.
---
# Enrich selected contacts

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

Resume private state. Show selected contacts and available emails. Reuse an
existing professional email after selection, without buying it again. Prepare
`prospecting-propose` for people.reveal_email only for missing selected emails.
Explain known/unknown credits and bounded quantity; the seller authorizes that
specific scope. Before approval, use proposal-bind-native with the real tool's
arguments and mapping from selected external identities, for example
items.<local-id>.external_ref.object_id. Approve the returned revision/digest;
execute through prepare-action, the exact native tool using
payload.native_request.input, and record-result. Do not send the domain envelope
to the provider, alter arguments after approval or bypass a hook denial.

Save source, time, returned field and external identity. Do not treat unavailable
or unverifiable email as found. Continue to a CRM proposal including selected
accounts, contacts, relationships and the requested owner; never write implicitly.

Use only the connected prospecting provider for missing professional email data.
Do not scrape search engines, public documents or social profiles for emails, and
do not infer an address pattern. Generic corporate mailboxes do not satisfy a
request for an executive's email. A provider's returned/verified status is reported
precisely; “found” does not mean deliverable or current without that evidence.
If provider access is blocked, preserve selected people and resume connection
assistance instead of continuing with public-web alternatives.

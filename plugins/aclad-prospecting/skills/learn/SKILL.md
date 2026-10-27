---
name: learn
description: Persist a real seller correction, distinguish personal preferences from account facts, review inferred candidates, or revoke an obsolete rule. Also apply within other skills when a seller corrects generated output.
---

# Learn

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

Follow [the common session protocol](../../references/session-protocol.md): resolve
the trusted instance, run `resume`, recover pending work and read only relevant
active rules. The seller uses chat; the skill invokes the runtime in the configured
private state directory. Missing persistence is reported, never replaced with an
in-memory promise to remember.

## Capture a real correction

Identify what changed, the seller's instruction and a durable evidence ID. Capture
a short before/after difference, not a chat transcript. No edit, unchanged output,
no reply or an approval to send does not establish a reusable preference.

Distinguish these scopes:

- `personal:email`, `personal:briefing` or `personal:all`: how this seller wants
  reusable outputs written. Set `explicit=true` only when they explicitly request
  a general personal preference. “Sempre evite esta expressão nos meus e-mails”
  requests a reusable preference and is explicit, even when spoken during draft
  review. A change requested only for the current text is inferred (`explicit=false`).
  Decide from the seller's stated scope, never from approval to send or silence.
- `account:<id>`: a fact or correction specific to one company. Save its evidence
  in that account's context; it never becomes a personal writing rule.
- `partner:product`: a correction about the partner's offering. It remains a
  candidate for review; this capture cannot silently change product positioning.

Internally, invoke the allowlisted `learn` command with JSON:

```json
{"before":"Long opening paragraph","after":"Keep my opening to one short sentence","scope_kind":"personal:email","explicit":true,"evidence_id":"correction-42"}
```

The `learn` command atomically stores the rule version, evidence and event.
Explicit personal preferences become `active`; inferred, account and product
corrections remain `candidate`. Repeated content in the same scope keeps one
rule with all distinct evidence. Reusing the same evidence ID for a different edit
is rejected. Do not claim a preference was saved unless the runtime confirms it.

## Use and review

Before generation, call `rules` with `{"scope_kind":"personal:email"}` (or the
appropriate scope). Only active relevant rules guide generation. `personal:all`
also applies to email and briefing; email-specific preferences do not affect a
briefing. Account and product candidates remain contextual evidence until their
own review process; they are not activated by asserting `explicit=true`.

Ask for validation when proposing an inferred general preference. Record that
confirmation as new evidence of the personal correction; the matching candidate
can then become active. Current seller instructions resolve preference conflicts,
without overriding commercial exclusions, budget, approval or send controls.

Use `revoke-rule` with the rule's current ID/revision and a short reason:

```json
{"rule_id":"rule-id-returned-by-runtime","revision":2,"reason":"The seller changed their preferred email structure"}
```

Revocation preserves evidence and history; revoked rules no longer guide output.
Capturing a matching correction does not revive a revoked rule. Review obsolete
rules selectively rather than loading every correction into every session.

## Keep it private and recoverable

Checkpoint after the completed block. Source examples, account corrections and
personal preferences stay in the seller's private state. Never append real data
to the distributed `../../knowledge/learned-rules.md`, `../../knowledge/examples/` or `record/`.
Readable reports are generated projections, not the authoritative state. No
cross-seller or cross-partner learning; optional sharing requires a reviewed export.

## Evidência de resultados neste projeto

O runtime prepara observações automaticamente, mesmo sem invocar learn. Depois
  dos envios/respostas, use `outcome-context` com campaign_id e task=email para ler
  as observações locais; isso continua permitido após pausa ou DNC. Não use
  `generation-context` como consulta de resultados: ele prepara uma nova abordagem
  e mantém os bloqueios de contato. Se status=refresh_required, execute resume ou
  checkpoint e consulte novamente. Para uma hipótese geral da campanha, use
  proposal_context e evidence_ids do topo, preservando todos os cohorts e o
  denominador completo. As linhas servem para revisão segmentada declarada, nunca
  para selecionar apenas sucessos. `outcome-propose` recebe context=proposal_context,
  evidence_ids=evidence_ids e instruction=hipótese curta. São IDs de
  observações, nunca IDs de ações, envios, respostas ou calendário. Não acrescente
  campos, source_ids ou descritores ausentes ao contexto; contexto legado vazio
  não permite inventar uma regra. Apresente amostra inteira, denominador, cobertura,
  época, negativos, ausências e limites observacionais antes de propor. Revise a versão exata da candidata com o
vendedor antes de `outcome-review` approve. Uma resposta positiva isolada não prova
eficácia e os dados não são um teste A/B. Regras ativas válidas podem ser reutilizadas
no mesmo escopo sem repetir confirmação; revogadas não são reativadas por novos dados.
Mantenha negativos e divergências. Prefira atribuição à sequência quando houver
vários toques. Proponha mudanças de ICP/cadência/persona para os fluxos revisados
existentes, sem alterar campanhas congeladas. O aprendizado é privado nesta pasta,
registrado no SQLite e projetado em contexto/aprendizados.md; nunca nos resultados
numéricos, ZIPs, Git ou serviço remoto. Não edite skills/hooks/política para aprender.

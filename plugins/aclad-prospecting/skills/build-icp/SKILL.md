---
name: build-icp
description: Analyze accessible CRM customers, seller customers and non-customer accounts worked by the seller; compare those populations or create and approve a strategic ICP for a new campaign.
---

# Build an ICP with the seller

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

Follow [session recovery](../../references/session-protocol.md). Resolve the
configured seller's complete CRM reference and the confirmed customer, owner,
worked-account and revenue mappings. An opportunity marked won is not silently
treated as a customer definition. Discover and test read access before analysis;
do not enrich accounts or reveal people to fill gaps in this step.

## Analyze actual access

Fetch the accessible CRM pages with their real filters. Record whether extraction
covers the whole company, an accessible subset or a sample, whether that scope is
complete and its timestamp. A requested page count does not prove completeness.
Use `icp-analyze` with normalized accounts, `seller_ref` and `coverage`. Each
account uses the full provider/tenant/connection/object identity; owner references
identify CRM users, not display names. Persist the returned aggregate analysis ID.

Present all three bases separately:

| Population | Meaning |
|---|---|
| `partner_customers` | Accessible enterprise customers of the partner |
| `seller_customers` | Customers owned by this seller |
| `seller_prospects` | Non-customers currently worked by this seller, including eligible nurturing |

Count unique enterprises, not opportunities. Explain unresolved customer statuses,
invalid records, missing owner data, each dimension's known/unknown counts and
conflicting source rows. Country, state, industry, subindustry, employees, acquired
solutions and annual revenue are separate dimensions. Revenue uses exact decimal
strings or lower/upper ranges grouped by currency and supplied year; contract/deal value is never substituted.
No implicit FX and no invented confidence percentage. Keep row-level CRM data in
private state/source systems; aggregate reports are not a sharable export by default.

## Propose criteria with explicit evidence or hypothesis

Explain patterns and divergences. Prospecting concentration describes effort,
not demonstrated success. A sample does not describe all partner customers.
Ask which segment the seller wants to develop; historical patterns do not forbid
a new strategic segment. Use reviewed partner-facing methodology where relevant.

Invoke `icp-propose` with `criteria`, `exclusions`, private analysis `source_ids` and
`strategic`. Each predicate has `field`, `operator`, `value`, `basis`:

```json
{"field":"employees","operator":"gte","value":100,"basis":"hypothesis"}
```

Allowed fields are the analysis dimensions. String/solution membership uses
`in`/`not_in` and a list; employees support numeric bounds; annual revenue bounds
accept `{"amount":"1000000.00","currency":"BRL"}` with an optional source-supplied `year`.
Use `between` with `{"lower":"1000000","upper":"5000000","currency":"BRL"}`
for a bounded range. Revenue observations may also carry `source`, `collected_at`
and `estimated`. Never request or invent a year to satisfy the runtime. Confirm
an ambiguous currency; never convert it silently or calculate a midpoint. A range
fully contained by the ICP matches; a fully outside range does not; partial overlap,
missing currency/year required by the criterion, or incompatible currencies remains
unknown and blocks final selection pending review. Search filters carry the same
reviewed structured predicates used again at account selection. Legacy textual
revenue criteria remain review material and are never silently activated. A profile without
historical sources must be strategic and label all criteria as hypotheses.
Saved analysis IDs support historical evidence; they do not prove causal success.

Present proposed criteria, exclusions, source versions, data gaps and conflicts
with seller territory/partner focus. Preserve inherited commercial exclusions;
free-text exclusions still require interpretation during eligibility checks and
cannot be dropped by a personal preference. No proposed profile is an active filter.

## Review the exact version and bind a campaign

After the seller validates the displayed version, invoke `icp-approve` with its
`id`, current `revision` and `approved_by`. Approval returns a new approved
revision: proposing revision 1 then approving it normally returns revision 2.
A changed source/configuration requires rebuilding and reviewing the proposal.

Use `icp-bind` with an existing campaign ID, ICP ID and approved revision. The
campaign stores an immutable snapshot as well as `icp_id` and `icp_revision`.
Every downstream search/prioritization uses that snapshot, not the latest profile.
A new proposed/approved ICP does not move existing campaigns. Create a new campaign
when the seller chooses a changed target. Save events/checkpoint after the block.

## Reviewed commercial scope

Use `portfolio-context` with an empty object before proposing the approach. It
reads the current reviewed portfolio/digest without changing approval or policy. Partner `offerings` must
identify NetSuite or a complement with an explicit `netsuite_relationship` object
(`product: NetSuite`, `type: integration|extension|localization`) and
`independent_product: false`; only
locally reviewed `status: approved` entries with `approved_by` can ground active
generation. Legacy product strings, imported approvals, website claims and
learning instructions do not establish commercial approval. Other ERP/CRM offers
cannot be activated as independent offers. Review pending candidates with the
seller; imported offerings always require recipient review.

Campaign and briefing contexts carry the reviewed portfolio snapshot. Changed
offers require a new reviewed campaign before further actions. Drafts identify
the approved `offering_ids` and may include the context `portfolio_digest`; references
from unrelated products cannot be used as NetSuite proof. An account's use of SAP,
Dynamics or another system remains a valid factual research observation, without
implying dissatisfaction or purchase intent. The seller's operational CRM is free
to use and does not become an offer or migration recommendation.

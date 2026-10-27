# Internal runtime contracts

## Descoberta sem estado

Antes de executar um comando ainda desconhecido, use internamente `python3 -m aclad
help`, `schema COMMAND`, `schema profile` e `examples COMMAND`, com PYTHONPATH
absoluto do runtime instalado. Não precisam de stdin, workspace, banco, registro
ou conexão. Os parâmetros vêm de COMMANDS e das assinaturas reais; o perfil deriva
do validador PROFILE. Objetos abertos continuam sujeitos aos validadores/gates.
As [receitas do operador](operator-recipes.md) encadeiam os retornos reais. Exemplos
são fictícios: não comprovam ferramentas, fatos, consentimento ou efeito externo.
O vendedor usa linguagem comercial; não recebe JSON, comandos, IDs ou citações
técnicas em outro idioma para conseguir responder à entrevista.


The seller uses chat. Resolve the installed plugin root, then set the helper's
PYTHONPATH to its absolute runtime path and invoke `python3 -m aclad` with one
command. Project commands resolve the local marker from native cwd/--workspace;
explicit --state-dir/--partner-id/--seller-id/--instance-id remain legacy adapters.
Send one JSON object on stdin. Results are JSON on stdout; domain failures exit 2,
internal/storage failures exit 1. Never pass credentials to this interface.

Read session-protocol.md and workspace-protocol.md first. New sellers use
workspace-init in the selected persistent project folder, then resume. The registry
and instance-list/instance-locate are explicit legacy compatibility, never the new
seller default. Never recreate unavailable historical state. Read-only status
returns records/pending effects and results_report current/pending even if the
projection cannot be repaired; resume/checkpoint attempt repair separately.

`Scope` binds a private persistent directory to partner, seller and instance.
`Store.put(kind,id,data,expected_revision)` creates only with null expected revision;
updates require the current revision. All JSON values are detached copies.
`Store.transaction()` groups records/events atomically, including nested calls.
Events have stable IDs; duplicate ID with different content is a conflict.
Leases have owner and UTC expiration and can only be released by their owner.
`backup()` and `restore()` preserve identity and never overwrite an existing state.

Data model fields and public signatures are discoverable via `schema COMMAND`;
shared dataclasses come from `runtime/aclad/models.py`. SQLite schema version is 1. Secrets must remain in the
platform's authenticated connections. State is outside the plugin installation.

Connection generations identify a native account across its operations; read,
draft and send bindings retain separate verification. A reconnect invalidates
the former generation. Candidate observations update allowlisted descriptive
fields only; restrictions, enriched provenance, CRM links and history survive.

`crm-item-prepare` emits one approved change and a stable `operation_id`. An
overlapping unknown/in-flight CRM effect blocks new proposals' execution.
Reconciliation observations need complete actual fields/links/owner, evidence
and the target reference; updates require a changed revision, creates unique
operation correlation. Absence or an unchanged object never proves success.

`review-resolve(action_id, expected_revision, contact_revision, account_revision,
decision, evidence_id, now, resume_account=False)` resolves a pending reply/date
review. Decisions are respond/keep_paused/resume_sequence/close. Respond returns
a single-use decision for `message.reviewed_response_id`; it binds one draft,
does not resume the sequence, and never removes DNC/address/manual restrictions.
Sending still requires a new exact-content approval and fresh reviewed/latest
reply IDs matching that decision. A new event or state revision invalidates it.

An explicit negative `environment-check` is enforced at the execution gate,
including paid operations. Hosts must run that diagnosis from verified facts
before commercial use; absence of a diagnosis is not evidence of durable hosting.

## Workspaces e resultados locais

`--workspace PATH workspace-init` recebe `{name}`; `workspace-locate` resolve marcador
ancestral. `workspace-migration-preview` recebe `{instance_id}` e `workspace-migrate`
recebe `{instance_id, preview_digest}`. A pasta é selecionada pelo host, nunca por
conteúdo importado. Marcador quebrado/banco ausente não caem no registro global.
Veja [protocolo de workspace](workspace-protocol.md).

`meetings-record(campaign_id, evidence_id, observations)` exige calendar.read salvo
bem-sucedido e completo. Cada item do resultado mapeia ref completo, source_revision,
status, starts_at, ends_at e participant_refs; observações devem corresponder ao item
e aos contatos com envio comprovado. Fonte/tenant/conexão e revisões são verificados.
`generation-context` recupera regras ativas/exemplos autorizados para o passo/tarefa.
`outcome-context(campaign_id, task="email")` lê observações locais mesmo após
pausa/DNC. Retorna amostra, janela, atribuição, limitações e, por linha,
proposal_context/evidence_ids prontos. Para hipótese geral, use os campos do topo:
contexto comum e TODOS os IDs, sem filtrar cohorts positivos. status=refresh_required exige resume ou
checkpoint antes de consultar de novo. proposal_context nulo não permite inventar
descritores para histórico antigo. Essa leitura não passa por generation-context,
que continua bloqueando uma nova abordagem a contatos pausados.
`outcome-propose(context, instruction, evidence_ids)` cria candidata usando
context=proposal_context e IDs de observações retornados, nunca IDs de ações;
`outcome-review(rule_id, revision, decision, evidence_id)` revisa approve/reject/revoke.
`outcome-rules(context)` recupera somente regras ativas válidas no escopo completo.

### Diagnóstico do host (objeto facts)

`environment-check` recebe `{facts: {...}}` com `surface` (identificador real do
host local), `runtime_version` (versão Python observada), `durable_state`,
`state_accessible_to_executor`, `identity_resolved`, `tools_verified` e
`scheduler_verified` (booleanos comprovados). Verificar fatos antes de marcar true;
conexões ainda não testadas ou scheduler indisponível permanecem false. Reexecutar
o diagnóstico depois de verificar conexões; um resultado negativo é aplicado no gate.

## Contratos 0.4 — configuração, pesquisa e personalização

Todos recebem JSON pelo adaptador; o vendedor não escreve esses objetos.

| Comando | Argumentos |
|---|---|
| `connections-prepare-probe` | `capability` exato do binding atual persistido, inclusive custo; apenas intent gratuito, nenhum fornecedor executado |
| `portfolio-context` | objeto vazio; leitura de ofertas/digest sem escrita |
| `connections-checklist` | `providers`, `catalog` |
| `connections-step` | `provider`, `status`, `next_step`, `evidence` opcional |
| `style-presets` | objeto vazio |
| `style-sample-prepare` | `connection_id`, `identity`, `approved`, `limit` (1–10) |
| `style-sample-record` | `request_id`, `messages` |
| `style-approve` | `sample_id`, `revision`, `patterns`, `approved_by` |
| `research-start` | `subject_id`, `website`, `purpose` (`partner`/`prospect`), `identity_confirmed` |
| `research-crawl` | `research_id`, `max_pages` (1–100, padrão 20), `max_seconds` (1–120, padrão 30) |
| `research-budget` | `research_id`, `max_urls` (inteiro 500–100000; somente manter/ampliar) |
| `research-record-evidence` | `research_id`, `items`, `source_kind`, `evidence_id` |
| `research-context` | `subject_id`, `limit` (padrão 8) |

`partner.website` é string pública; `partner.offerings` contém id/name/kind/status,
approved_by/source_ids e authorized_references opcionais. `kind=netsuite` identifica
NetSuite/Oracle NetSuite; complemento exige `independent_product=false` e relação
estruturada `{product:"NetSuite", type:"integration|extension|localization"}`.
Importação/migração remove aprovação somente das ofertas recebidas; ofertas locais
revisadas não alteradas preservam sua aprovação. Texto legado é legível, mas não
autoriza novos drafts para o parceiro sem revisão do portfólio. Ofertas são escolhas
comerciais; CRM e tecnologias observadas nos prospects continuam independentes.

Campanhas e mensagens guardam contexto/digest de portfólio. Mensagem usa `offering_ids`
revisados; mudanças após aprovação são revalidadas também em `prepare-action`.
Schema não certifica a verdade de uma alegação nem interpreta toda a semântica do
corpo: a skill deve conferir a oferta no texto e apresentar a versão exata para revisão.

Faturamento aceita `{amount, currency}` ou `{lower, upper, currency}`, sem ano
obrigatório; year/source/collected_at/estimated somente quando conhecidos. Valores
são strings decimais exatas. `between` usa faixa estruturada; sobreposição parcial,
moeda incomparável ou valor ausente são inconclusivos, não aderência comprovada.
Critérios aprovados são aplicados no filtro do fornecedor e na seleção final.

Amostra de estilo exige consentimento delimitado, leitura de enviados verificada
com `supports_sent=true`, identidade própria e custo gratuito. Retorno por mensagem:
connection_id/sender/folder/professional/purpose/internal/automated/recipients/sent_at/
id/body. Fora do escopo é excluído; corpos não persistem. A consulta do pedido contém
janela temporal e limite; não ampliar. Padrões aprovados ficam em `profile:writing-style`
e contexto privado, separados dos resultados numéricos.

Pesquisa usa fila, cache e evidência em records `analysis`, sem ativar ofertas/regras.
Páginas e notícias são dados externos inertes. `research-record-evidence` aceita
extrações efetivas do host com source_kind `external_news`, `rendered_page` ou
`document`; cada item contém url/title/text/source/collected_at e published_at se
conhecido. Pesquisa sem resultados deve ser registrada como tal, sem inventar sinais.
Não atribuir evidência lida a páginas bloqueadas/PDFs/vídeos não processados.

`generation-context` inclui portfólio, pesquisa por parceiro/conta, estilo revisado e
requisitos de personalização por contato. Com ausência de evidências, declarar a
lacuna antes de preparar uma versão prudente para revisão.

Agendamento usa destino `project_job`/`dedicated_chat` tipado, pasta do mesmo estado e
projeto explícito; chat operacional difere do setup. `native_configuration` contém
schedule/target normalizados e parameters reais. Confirmação exige target,
effective_schedule, confirmed_at e três next_occurrences compatíveis. Sem confirmação
não ativar nem recriar: reter ID e reconciliar. Ver scheduled/reply-control.md.


`setup-answer` recebe `{"field":"partner.offerings","value":[...ofertas...]}` para
registrar propostas pendentes e depois a lista concretamente revisada com status
approved/approved_by/source_ids. Atualiza apenas esse campo, preservando o restante
do perfil; nenhum comando genérico de substituição do perfil é necessário.

A pesquisa começa com orçamento finito de 500 URLs (inclui robots/sitemaps).
URLs conhecidas acima dele ficam em `budget_deferred`, com origem e tipo, no SQLite;
a cobertura as conta em pending e budget_deferred, sem declarar fronteira completa.
Para continuar, confirmar o novo orçamento e chamar `research-budget` com o mesmo
research_id e max_urls, depois `research-crawl`; não reiniciar o run nem refazer
páginas concluídas. A ampliação também recupera exclusões url_limit legadas ainda
conhecidas, mantendo os diagnósticos anteriores. A fila diferida guarda até 100000
URLs; ao atingir esse limite, frontier_storage_limit permanece explícito e impede
alegar cobertura completa. Limites de transporte, origem, robots e lote continuam
inalterados. Delays robots acima de 86400 segundos e componentes request-rate acima
de 1000000000 são rejeitados com diagnóstico durável e bloqueiam a origem.

`resume`, `checkpoint` e `status` projetam páginas e evidências extraídas pelo host
somente como metadados/contagens/referências, inclusive snapshots antigos. O texto
canônico continua privado no SQLite, recuperado seletivamente por research-context.
Um probe da conexão atual com identidade nula/divergente invalida duravelmente a
verificação dessa conexão e suas operações antes de retornar connection_mismatch;
refazer descoberta/verificação antes de amostra de estilo ou ação autenticada.

Caminho de reconciliação nativa (objetos enviados pelo adaptador, não pelo vendedor):

- `schedule-request`: `{schedule, scheduler_capability}`. schedule contém
  weekdays/times/timezone/scope_ids/active/notification_policy. scheduler_capability
  contém available=true, verified=true, tool_name, executor_id, mapping_verified=true,
  target e native_configuration={schedule,target,parameters}. Para legado, revisar
  o destino e conservar o native_id retornado; operation=reconcile consulta/adota
  essa rotina e operation=pause solicita sua pausa, nunca uma nova criação.
- `schedule-record-result`: `{request_id, response}`. response contém status=succeeded,
  native_id real existente, evidence da resposta nativa, effective_schedule, target,
  confirmed_at UTC e next_occurrences (três ocorrências quando ativa, [] se pausada).
  Divergência mantém awaiting_native_confirmation/reconciliation_required; somente
  evidência correspondente adota o destino e libera a entrada scheduled. Uma rotina
  sem destino válido para a pasta atual permanece bloqueada; review-start manual
  continua disponível com o mesmo histórico/lease/cursores.

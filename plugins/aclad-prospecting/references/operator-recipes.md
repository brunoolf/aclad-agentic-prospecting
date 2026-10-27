# Receitas do operador ACLAD

Esta página é interna ao assistente. O vendedor fala sobre negócio no próprio
idioma; não recebe comandos, JSON, IDs técnicos ou exceções em inglês. Explique
somente o limite comercial e o próximo passo necessário. Faça poucas perguntas
relacionadas por rodada e aproveite respostas e contexto já salvos.

## Descobrir antes de executar

A raiz do plugin é `../..` a partir de `skills/<nome>/SKILL.md`; a pasta de estado
vem do contexto confiável do host e é outra localização. Configure o processo
interno com PYTHONPATH absoluto apontando para `<raiz-do-plugin>/runtime`.
Python 3.11+ deve estar disponível; não instale pacotes globais.

```text
python3 -m aclad help
python3 -m aclad schema setup-answer
python3 -m aclad schema profile
python3 -m aclad examples setup-answer
python3 -m aclad schema generation-context
python3 -m aclad examples send-propose
```

`help` lista o catálogo real. `schema COMMAND` lê a assinatura do handler atual,
com obrigatórios/opcionais e dataclasses; `schema profile` deriva do validador do
perfil. `schema setup-answer` também lista caminhos e tipos e relaciona field/value.
`examples [COMMAND]` mostra objetos fictícios. Todos funcionam sem stdin, workspace,
SQLite, registro global, credenciais ou serviços. Não leem o estado do vendedor.
Um objeto aberto no schema não elimina validação semântica ou gates do domínio.

Não use funções Python como nomes CLI. As ações usam hífens: `style-presets`,
`style-sample-prepare`, `style-sample-record`, `style-approve`, `generation-context`.
Use somente referências ligadas pelas skills e pelo catálogo abaixo; não existem
`tool-protocol.md` ou `crm-protocol.md`. Ao receber invalid_arguments/invalid_profile,
consulte o schema e o exemplo antes de tentar novamente; não leia repetidamente a
implementação nem tente campos ao acaso.

`connections-prepare-probe` recebe capability completo e exato retornado por
connections-discover, compara-o com o binding atual salvo (custo, ferramenta e
geração inclusive) e retorna somente intent local de leitura gratuita; não chama o fornecedor, confirma
autenticação ou grava prova de acesso. `connections-record-probe` só depois do
retorno real da leitura mínima nativa. Escrita, reveal, envio, custo pago ou
desconhecido não cabem nesse probe e mantêm a ponte normal de aprovação/custo.
`portfolio-context` recebe objeto vazio e retorna apenas a leitura validada das
ofertas, pendências e digest atuais, sem ativar uma oferta ou mudar checkpoint.

Exemplos não são uma execução nem prova de consentimento. Substitua cada ID,
revisão, digest, referência, data e fato pelos retornos reais da mesma pasta e
conexão. Não registre um resultado fictício para satisfazer um gate.

## Jornada e fontes de cada argumento

| Etapa | Comandos e origem dos argumentos |
|---|---|
| Entrar | `workspace-init` recebe name em pasta persistente comprovada; `resume` recupera o estado existente. Marcador quebrado exige recuperação, nunca novo banco. |
| Configurar | `setup-next` indica campos pendentes; `setup-answer` recebe um field e seu value no tipo de `schema profile`. Nome e site são strings salvas separadamente. |
| Pesquisar parceiro | `research-start` recebe subject_id confiável do parceiro, website confirmado, purpose=partner e identity_confirmed. `research-crawl` continua o mesmo research_id; `research-context` recupera evidência. |
| Rever portfólio | `portfolio-context` lê ofertas revisadas/digest sem escrita; `setup-answer` em partner.offerings guarda primeiro pending_review. Fontes não ativam ofertas: apresentar proposta concreta e só então guardar a versão revisada. |
| Conectar | `connections-discover`, `connections-prepare-probe`, `connections-record-probe`, `connections-checklist` e `connections-step` usam ferramentas e identidades observadas. Catálogo não prova autenticação nem custo gratuito. |
| ICP e lista | `icp-analyze` separa as três populações com seller_ref/coverage reais; `icp-propose`, `icp-approve`, `campaign-create`, `icp-bind` preservam a versão revisada. `prospecting-propose` e a ponte executam busca; `candidates-record`, `accounts-select` guardam somente resultados e escolha reais. |
| Conta e pessoas | `account-check`/`account-eligibility` verificam histórico; `research-start` purpose=prospect e `research-context` informam personalização. `roles-confirm`, busca aprovada quando paga, `contacts-select`, enriquecimento e `enrichment-record` mantêm os gates. |
| CRM | `crm-propose` apresenta campos/owner/links concretos; `approve` aprova a versão; `crm-item-prepare` prepara um item, ferramenta nativa executa, `crm-item-record` salva evidência. Incerto exige `crm-reconcile`. |
| Preparar texto | `outreach-plan` guarda passos revisados. `generation-context` recebe campaign_id, account_id, contact_id, task=email, plan_step_id. Não recebe um objeto context, operation ou message. |
| Criar rascunho | `draft-propose` recebe campaign_id e message completo. Mostrar texto/destinatários, aprovar criação com `approve`, usar `prepare-action`, executar intent nativo, registrar `delivery-record`. |
| Enviar | `send-propose` recebe draft_ref completo, current_draft e preflight atuais. Não recebe campaign_id/message no topo. Exige outra aprovação exata, novo preflight, `prepare-action`, ferramenta e `delivery-record`. |
| Conferir | `review-start`, `review-apply`, `review-finish` compartilham histórico/lease. `review-resolve` resolve uma pendência revisada, sem autorizar envio sozinho. |
| Reuniões | Salvar calendar.read bem-sucedido completo e então `meetings-record` com campaign_id, evidence_id dessa ação e observations. E-mail sobre reunião não comprova evento de calendário. |
| Aprender | Correção explícita reutilizável usa `learn` com explicit=true; edição isolada fica candidata. Resultado usa `outcome-context`, `outcome-propose`, depois revisão separada `outcome-review`. |
| Programar | Testar conferência manual e host; `schedule-preview`, `schedule-request`, ferramenta oficial e `schedule-record-result` vinculam mesma pasta/projeto e destino revisado. Preferência não confirma job. |

## Campos do setup sem adivinhação

`item_ids` de `proposal-create` e `prospecting-propose` nunca é uma lista vazia.
Para a busca de contas, use o ID da campanha já criada; para consultar empresas
selecionadas, seus IDs locais. Uma consulta de metadados/análise anterior à campanha
usa um identificador da própria consulta e filtros explícitos do conector, sem
apresentá-lo como ID de empresa. O identificador registra o escopo da intenção,
não comprova autenticação, seleção, consentimento ou existência de um registro.

Em `partner.offerings`, `kind=netsuite` usa o nome canônico `Oracle NetSuite` ou
`NetSuite`. Os serviços de implantação/suporte ficam na lista `partner.services`,
sem mudar a identidade do produto. Complementos preservam nome/vínculo NetSuite
estruturado e sempre passam pela revisão comercial.

`partner.name`, `partner.website`, `seller.name`, `seller.portfolio` e
`seller.writing_style` são strings. `seller.territory`, `seller.size_bands` e
`tool_suggestions` são listas de strings. `seller.portfolio` não é objeto/lista de
contas. `partner.name` não recebe `{name, website}`; faça duas chamadas. Campos como
partner.id ou seller.email não fazem parte do perfil. A identidade vem do workspace
ou da conexão observada. O vendedor não deve fornecer IDs internos do CRM.

`schedule_preferences.mode` aceita manual, scheduled ou combined. Use o schema
para demais campos; não transforme preferências em scheduler confirmado.

## Mensagem, aprovação e resultado são objetos diferentes

Na amostra de enviados para estilo, entregue os dados transitórios diretamente a
`style-sample-record` antes de registrar o recibo da ação. `record-result` dessa
leitura aceita apenas metadados numéricos/booleanos: `complete` e `sample_count`
iguais ao resumo canônico, com `excluded_count` opcional. Preserve action_id,
status e external_refs reais. Corpos/assuntos/destinatários e campos desconhecidos
são rejeitados pelo runtime; não os copie nem substitua contagens por estimativas.

`examples draft-propose` traz o envelope completo: campaign_id e message com
account_id/contact_id, sender_ref, to/cc/bcc, subject/body, attachments, source_ids,
plan_step_id e offering_ids revisados. `examples send-propose` traz draft_ref e
current_draft, com external_revision do provedor. Preflight registra o estado
atual verificado, nunca flags presumidas. Anexos não verificados são bloqueados.

`approve` usa proposal_id, revision, digest, approved_by e **approved_at**. Em
`prepare-action`, capability é o binding verificado inteiro, não apenas o nome da
operação; preflight e now são da execução atual. `delivery-record` recebe
**message_id e result**, onde result contém action_id, status, external_refs e data.
Não confunda message_id/proposal_id com action_id. Preservar conversation_ref real
é necessário para acompanhar respostas. Resultado incerto exige reconciliação;
um novo exemplo ou aprovação não elimina um efeito pendente.

## Reunião e aprendizado após pausa

`examples meetings-record` mostra observations com ref, source_revision, status,
starts_at, ends_at, account_id e contact_ids. participant_refs pertence aos itens
salvos do resultado calendar.read, não à observação local. Os valores precisam
coincidir exatamente com o resultado completo e com participantes de envio
comprovado; não misture revisão, conexão ou campanha.

Depois de respostas/reuniões, use `outcome-context` com campaign_id e task=email.
Essa leitura local permanece disponível após pausa/DNC. `generation-context`
prepara uma nova abordagem e continua respeitando os bloqueios de contato.
Se o retorno indicar refresh_required, use resume/checkpoint e consulte novamente.
Cada linha informa amostra, janela, atribuição, limitações, evidence_ids e
proposal_context. O topo também retorna proposal_context com os descritores comuns
e evidence_ids de TODOS os cohorts. Para uma hipótese geral da campanha em
`outcome-propose`, copie **context=proposal_context** e **evidence_ids=evidence_ids**
do topo, acrescentando instruction com a hipótese curta. As linhas são para revisão
segmentada declarada; não selecione apenas cohorts positivos. São IDs de observações de resultado, nunca IDs de ações,
reuniões, respostas ou mensagens. Não invente industry/size_band/persona/variant,
não acrescente source_ids ao contexto da regra. proposal_context nulo registra a
lacuna de um histórico antigo; não o substitua por palpite.

Apresente a amostra inteira, denominador, cobertura, época e limites observacionais,
inclusive negativos e silêncio não observado. Uma candidata não é uma regra ativa,
nem prova causal ou A/B. `outcome-review` recebe rule_id/revision atuais, decision e
evidence_id da revisão explícita da hipótese concreta. Aprender não retoma conta,
remove DNC, cria draft, envia, escreve CRM ou autoriza gasto.

## Referências existentes

- [Sessão e recuperação](session-protocol.md)
- [Workspace](workspace-protocol.md)
- [Conexões e ferramentas](connectors.md)
- [Contratos e invariantes](runtime-contracts.md)
- [Conferência e agendamento](../scheduled/reply-control.md)
- [Outreach](../skills/outreach/SKILL.md)
- [Aprendizado](../skills/learn/SKILL.md)

# Ponte entre runtime e ferramentas nativas

Python não herda acesso aos MCPs do modelo. A skill descobre nomes reais, associa
operações e normaliza o resultado: `prepare_action → tool_intent → chamada nativa
→ record_result`. Bindings fictícios nunca são conexões ativas.

Operações públicas: `crm.read`, `crm.write`, `accounts.search`,
`companies.enrich`, `people.search`, `people.reveal_email`, `email.read`,
`email.create_draft`, `email.send`, `calendar.read`. A função
`connections.canonical_operation` concentra os aliases de compatibilidade.

`connections-discover` recebe `visible_tools` com `tool_name`, `operation`,
`connection_id` nativo, `provider`, `account_identity` (tenant + identidade opaca,
sem credenciais) e `cost`; `visibility_complete` descreve a cobertura do inventário.
A descoberta não chama o serviço. Uma sugestão de fornecedor só registra operações
pretendidas, todas ainda não verificadas.

Registro `kind=connection`: ID `inventory-` seguido dos primeiros 24 dígitos do
SHA-256 de `native_connection_id + NUL + operação canônica`. Dados:
`capability` (campos do tipo Capability), `native_connection_id`, `provider`,
`account_identity`, `visibility_complete`, `observed_at` e último probe redigido.
A troca de identidade/provedor/ferramenta cria nova geração lógica de
`capability.connection_id` e invalida a verificação. A referência nativa continua
separada para o host. Propostas antigas não devem corresponder à geração ativa.

O resultado nativo recebe envelope de identidade proveniente do binding confiável
do host, jamais do texto de e-mail. `normalize-result` recebe `binding` com
`tool_name`, `operation`, `connection_id` lógico, `provider`, `tenant_id` e `result`
com mapeamentos de caminhos para `status`, `object_id` e campos `data`. `raw` deve
conter `connection_id` e `tenant_id` iguais. Resultado divergente é rejeitado;
sucesso sem ID externo comprovável fica `unknown`. O host não inventa IDs quando
a ferramenta não oferece evidência suficiente.

`prepare_probe` devolve somente intenção de leitura gratuita. O host executa o
probe e entrega a `record_probe` o status HTTP, conexão lógica e uma referência de
evidência sem corpo privado. 2xx sem evidência não vira verificação bem-sucedida.
Um resultado tardio de conexão antiga é recusado. Não persistir payloads brutos
com credenciais. Probes comerciais pagos precisam da ponte de aprovação normal.

Limite: este runtime não intercepta chamadas diretas feitas fora da ponte.
Usar aprovações nativas e hooks comprovados no host quando disponíveis.
# Verificações adicionais da versão 0.4

Para analisar estilo, o binding `email.read` precisa comprovar acesso a enviados
(`supports_sent=true`) na identidade do vendedor. Disponibilidade de inbox não
comprova essa capacidade. Respeitar o pedido `style-sample-prepare`, que delimita
folder/sender/janela/limite/prospecção profissional; não ler caixa inteira.

Para scheduler, o adaptador normaliza a configuração efetiva e destino, além dos
parâmetros reais. Confirmar pelo resultado nativo que projeto/pasta, dias, horários,
fuso e próximas ocorrências correspondem ao revisado. `mapping_verified=true`
sozinho não comprova isso. Não assumir suporte a chat recorrente fixo entre hosts.

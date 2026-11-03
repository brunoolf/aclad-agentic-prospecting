# Conexões por capacidade

O catálogo `connector-catalog.json` registra a data de cada fonte; monday, Snov.io
e o protocolo SMTP foram conferidos em 2026-10-26. As demais fontes conservam sua
data anterior. A presença na lista não demonstra instalação, autenticação,
entitlements, permissões nem uma operação disponível neste ambiente.

O host consulta as ferramentas visíveis e os mecanismos nativos de descoberta,
inclusive ferramentas diferidas e catálogo de plugins. Não ler arquivos de
credenciais. Inventário incompleto transforma ausência em `unknown`; inventário
completo permite `not_visible`, sem afirmar inexistência na conta ou computador.

Registrar por operação: ferramenta real, conexão, identidade da conta e provedor,
visibilidade (`visible`, `not_visible`, `unknown`), autenticação (`unknown`,
`authenticated`, `failed`), permissão (`unknown`, `allowed`, `denied`), evidência
(`declared`, `verified`, `failed`) e custo (`free`, `paid`, `unknown`).

Apenas leitura comprovadamente gratuita pode servir de probe automático:
`connections-prepare-probe` recebe capability exato e native_input com os argumentos
reais, que ficam presos à permissão de uso único consumida por PreToolUse. Depois
da leitura real, `connections-record-probe` salva a prova. Busca com custo
desconhecido usa os gates comerciais. Nunca enviar, criar dados
ou revelar contatos para testar acesso. Um 401 indica falha de autenticação; 403
indica permissão negada. Nome de ferramenta listado não prova acesso.
Resposta 2xx com evidência mas sem identidade comprovada na própria resposta não
verifica acesso. Identidade declarada pelo inventário não substitui essa prova.
Se a resposta identificar outra conta/usuário, rejeitar a associação. Redescoberta
com identidade ou ferramenta diferente invalida a geração e os testes antigos.

Orientar autenticação pela interface nativa da plataforma, com fonte oficial.
Não pedir senha, token ou API key no chat. Quando necessário, explicar habilitação
por administrador. Depois do login, redescobrir e validar a operação específica.
Escrever `.mcp.json` não autentica e não é uma configuração universal.

Se uma operação não funcionar, mostrar o impacto e permitir atividades independentes
(por exemplo, entrevista e pesquisa do site do parceiro ou de conta já mapeada;
nunca descoberta de empresas/pessoas/emails pela web). Não prometer disponibilidade de envio
porque existe leitura de e-mail; busca de pessoas não comprova revelação separada.

## Checklist que acompanha o vendedor

Usar `connection_checklist(store, providers, catalog)` para cada ferramenta citada,
inclusive uma desconhecida. O checklist fica privado no SQLite e mantém estado,
próximo passo e referência de evidência. `update_connection_step` permite registrar
bloqueio e tarefa concreta; uma atualização manual não declara autenticação.
Recalcular depois de login, troca de conta ou nova descoberta: verificação antiga
não se transfere. Nunca ocultar fornecedor porque ainda não consta do catálogo.
Mudança nas operações exigidas pelo catálogo também recalcula prontidão; `ready`
derivado nunca é reutilizado quando alguma capacidade requerida está pendente.

Separar conhecido (`known`), nível de suporte documentado (`support_level`),
instalado/habilitado (desconhecido quando sem prova), ferramentas descobertas,
identidades e operações verificadas. Cada operação conserva custo e permissão.
Leitura, escrita, draft, envio e calendário são capacidades independentes. O caminho
por família de host é orientação; sua disponibilidade precisa de descoberta atual.
Pipedrive continua reconhecido com documentação pendente, sem URL inventada.
Cortex exige nome do produto, fornecedor e site antes de atribuir capacidades.

Orientação oficial adicionada: [monday MCP](https://support.monday.com/hc/en-us/articles/28515034903314-Get-started-with-monday-MCP)
usa conexão e consentimento próprios; [Snov.io MCP](https://snov.io/knowledgebase/how-to-use-snov-io-mcp-with-your-ai-assistant/)
tem configuração por assistente. Nenhum desses caminhos foi autenticado neste piloto.
[SMTP](https://www.rfc-editor.org/rfc/rfc5321.html) é transporte/envio: sozinho não
oferece leitura de respostas nem amostra de enviados; identificar provedor e caminho
nativo antes de orientar credenciais. Não pedir tokens na conversa.

Em NetSuite confirmar conta comercial, NSCORP, ambiente demo/produção, usuário e role.
Usar metadados para descobrir campos/responsáveis e confirmar significado comercial
com o vendedor. Conectar o CRM escolhido para operação sem propor migração.

## Enviados e estilo

Uma ferramenta genérica `email.read` não comprova acesso a enviados. Registrar
`supports_sent: true` apenas quando a ferramenta e a conta realmente o permitirem.
Amostra exige identidade profissional própria, leitura gratuita verificada e aceite
explícito do escopo: até dez mensagens de prospecção enviadas nos últimos 90 dias,
sem internas, automáticas ou irrelevantes. O pedido expira em 24h, é de uso único e
fica preso à revisão/geração da conexão; sem acesso, usar presets ou exemplos dados
pelo vendedor. Não ampliar a busca ou guardar bodies da caixa para obter mais casos.

`record_style_sample` recebe só o lote consentido, filtra por identidade, conexão,
pasta, destinatários, classificação e data; guarda padrões heurísticos e referências
mínimas privadas. Não guarda corpo, assunto ou destinatários. `approve_style` exige
revisão explícita e versão correta antes de ativar a sugestão; o estilo privado não
é exportado com contexto do parceiro. Aprovação de email isolado não ativa padrão.

## Conexões mínimas do setup

Antes da primeira busca operacional, o assistente conclui um bloco só de conexões:
CRM com leitura comprovada; provedor de prospecção com busca de empresas e pessoas;
comunicação com leitura e recursos de draft/envio. Calendário é verificado quando
necessário para comprovar reuniões. Nome informado, plugin instalado e ferramenta
listada não comprovam acesso autenticado. Não faça writes/envios/reveals para testar.

CRM somente leitura é aceito; a gravação fica bloqueada quando necessária, com
orientação para habilitar uma conexão permitida. SMTP isolado não lê respostas.
Se uma ferramenta de prospecção estiver indisponível ou bloqueada pelo administrador,
ajude a conectar alternativa autorizada e mantenha a etapa pendente. A web não pode
substituir o provedor para listar empresas, descobrir pessoas ou obter emails.
Somente após mapear a empresa nas fontes operacionais a pesquisa contextual no
site/notícias é realizada, dentro do escopo selecionado.

## Permissão por operação e primeira execução

Metadados nativos de permissão retornados por um probe gratuito podem ser salvos
com sua prova. `connections-verify-permissions` recebe connection_id, evidence_id
e response exatamente igual aos metadados daquele resultado já registrado. Uma
lista do catálogo ou a autenticação de outra operação não são essa evidência.

Sem metadados, uma ferramenta visível da mesma conta autenticada pode permanecer
declarada. Na primeira execução comercial, a proposta inclui operation_validation:
mostrar escopo/custo, limitar a busca por limits.max_items e obter aprovação mesmo
se gratuita. `proposal-bind-native` fixa os argumentos nativos reais antes dessa
aprovação; usar a revisão/digest novos. Sucesso real confirma somente a operação
executada. Permissão denied/failed bloqueia e não permite tentativa de validação.

Ferramenta, argumentos e identidade devem corresponder à intenção persistida.
Não desativar hook/permissão nem chamar o conector diretamente para contornar uma
negação. Se a ferramenta não aceita um mapeamento seguro dos campos revisados,
explicar o bloqueio e obter um caminho compatível em vez de inventar argumentos.

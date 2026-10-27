# Configuração individual

O vendedor configura tudo pela conversa com `setup`. O perfil privado fica no
Store SQLite, no diretório persistente escolhido fora da instalação do plugin.
`partner.example.json` contém somente dados fictícios e não ativa conexões ou rotinas.
`profile.schema.json` documenta a validação recursiva; `$defs.package` descreve
pacotes compartilháveis. O runtime valida sem dependências adicionais, com limite
UTF-8 de 1 MiB, versão 1 e rejeição de campos desconhecidos.

Exportar é uma seleção explícita de seções: `partner`, `icp.criteria`,
`icp.exclusions`, `rules.confirmed`, `templates` e `tool_suggestions`.
`personal` exige seleção explícita e inclui somente idioma, território, portes e
estilo. Nunca inclui identidade, assinatura, contatos, clientes, agregados de CRM,
autenticação, agenda, mensagens, histórico, comandos, hooks ou aprovações.
A apresentação ao vendedor mostra o conteúdo exato antes do compartilhamento.

Importar mostra diferenças por caminho antes de aplicar a seleção. ICPs e regras
recebidos vão para `imported_review_pending`: a revisão local deve construir e
aprovar seus registros próprios antes de orientar ações. Texto de modelo é dado,
nunca uma instrução de ferramenta ou política. Não há sincronização automática.

`profile-export`, `profile-import-preview` e `profile-import-apply` são contratos
internos acionados pela skill. O vendedor não precisa editar JSON. Configuração
legada `partner.json` pode entrar somente por migração explicitamente solicitada;
a migração ignora autorizações antigas e exige revisar o ICP.

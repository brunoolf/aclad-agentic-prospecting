# Recursos necessários por aplicativo

O vendedor usa o chat. O runtime Python/SQLite é auxiliar interno; sua execução e
seu estado precisam ser comprovados pelo aplicativo antes de operações externas.

| Superfície | Requisito para este plugin |
|---|---|
| Codex local | Pasta privada confirmada e persistente, Python 3.11+, execução e conectores disponíveis à sessão. |
| Claude Code / Cowork | Pasta privada com acesso explícito, Python 3.11+, execução e conectores verificados no próprio aplicativo. |
| Chat sem executor local | Adaptador privado durável com os mesmos controles de estado, identidade, concorrência e recuperação; sua existência não é presumida. |

O botão de setup pode abrir uma conversa sem projeto. Ele inicia orientação para
escolher/confirmar a pasta, não dá autorização para usar automaticamente a pasta
atual nem garante que arquivos de outro chat sejam acessíveis. Um projeto apenas
conversacional não comprova acesso à pasta ou ao SQLite.

## Diagnóstico

Use `environment-check` com fatos comprovados do host. Sem persistência adequada:
`state_unavailable`. Sem runtime, identidade ou ferramentas necessárias: estado
limitado. Entrevista e orientação podem continuar para resolver o bloqueio, mas
novas ações pagas/externas e rotinas não ficam habilitadas por suposição.

Use `setup-status` para prontidão do fluxo: ambiente pronto não substitui os blocos,
a conexão autenticada ou aprovações por ação. As conexões mínimas são CRM de leitura,
prospecção e comunicação. Permissões de escrita, draft, envio, leitura de enviados,
calendário e custo são verificadas separadamente. CRM somente leitura é aceito no
setup; gravações continuam bloqueadas sem capacidade e aprovação.

## Interação

Perguntas estruturadas dependem das ferramentas expostas à sessão. Use
`request_user_input_async` no Codex quando disponível, `request_user_input` quando
permitido, e `AskUserQuestion` no Claude quando exposto. Não force modo/configuração
para obter um popup. Sem esse recurso, uma pergunta curta por vez no chat preserva
o mesmo bloco, estado e revisão. Não afirmar uma interface que não foi exibida.

## Rotina e retomada

O scheduler deve provar executor, acesso à mesma pasta, destino do projeto ou chat
operacional separado, programação efetiva e ID nativo. Preferências e intenções
salvas não comprovam ativação. Após uma troca de conta, redescubra capacidades e
resolva a identidade novamente. Sem scheduler, ofereça modo manual para escolha
explícita. Não use o chat de setup como destino padrão nem crie chats sem a
permissão exigida pelo host.

Dois bancos locais separados não sincronizam campanhas. Uma conversa em outro
aplicativo não herda autenticação ou aprovação. Hooks são reforço: cada skill deve
retomar/salvar pela ponte mesmo sem hooks. O runtime não intercepta uma chamada
nativa arbitrária feita fora dessa ponte.

Consulte a documentação oficial do aplicativo antes de orientar instalação ou
conexão; catálogo, teste local e exemplo sintético não certificam acesso real ao
fornecedor. Mantenha falhas, recursos ausentes e verificações não executadas visíveis.

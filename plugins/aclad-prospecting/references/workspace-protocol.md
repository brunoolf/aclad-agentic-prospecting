# Ambiente privado por pasta — protocolo 1

A pasta escolhida no contexto confiável do host é a unidade de instalação privada.
O plugin instalado fornece o runtime compartilhado. Não copie seu código/cache para
cada projeto. Python 3.11+ e execução/persistência locais precisam ser diagnosticados;
um host sem esses recursos deve informar a limitação na conversa, sem instalar
Python ou dependências globalmente.

No primeiro uso, invocar setup e executar `workspace-init` com `--workspace` obtido
do host. Mostrar os arquivos criados e orientar nova conversa se necessário para
carregar AGENTS.md/CLAUDE.md. Na mesma conversa continuar com entrevista progressiva,
`setup-next` / `setup-answer`, retomando respostas já salvas. Dados externos não
escolhem caminhos. Se instruções anteriores conflitarem, mostrar prévia antes de
substituir seu bloco gerenciado; preservar o conteúdo do vendedor.

Nas sessões seguintes, resolver o marcador ancestral do cwd e executar `resume`
antes de cada skill; fazer `checkpoint` durante o trabalho e antes de compactação.
Marcador inválido ou banco desaparecido gera `state_unavailable`: recuperar backup,
nunca criar uma instância nova por suposição nem usar outra instância global.

Estrutura privada: .aclad/workspace.json, state.sqlite, backups/, contexto/empresa.md,
vendedor.md, resultados.md, aprendizados.md; planos/, campanhas/, relatorios/.
Permissões locais restritas. Não inicializar Git; quando já existir, sugerir exclusão
dos dados privados sem editar o .gitignore automaticamente. Não compartilhar a pasta.

Registro global legado continua até migração explícita: escolher instância, mostrar
`workspace-migration-preview`, origem/destino/contagens/backup, confirmar a prévia e
executar `workspace-migrate`. Migração congela a origem, verifica a cópia e evita dois
bancos graváveis; interrupção é retomada pelo journal, sem apagar o histórico.

Hooks aprovados usam o mesmo marcador; fora da pasta não iniciam onboarding. Sua
confiança é controlada pelo aplicativo. SessionEnd Codex tem 3 segundos e não é o
mecanismo principal de persistência. Sem hooks, o bootstrap explícito é obrigatório.
Se plugin ausente/desabilitado, orientar instalação/ativação, sem fingir execução.
Codex, Claude Code e Cowork precisam de evidência individual de arquivos e execução.

`contexto/resultados.md` contém apenas rótulos fixos e contagens/taxas acumuladas,
sem nomes, dados de empresas, IDs, hashes, links ou conteúdo comercial. SQLite é
canônico; edição do Markdown é substituída pelo cálculo seguinte. Atualização é
obrigatória após transições, sem depender de hooks. Falha posterior a um efeito
confirmado gera results_report_unavailable e bloqueia novas ações pagas/externas;
nunca repetir o efeito. Persistir evidência/reconciliar/diagnosticar permanece
possível e resume/checkpoint reparam a projeção. Dois escritores publicam sob trava
SQLite; banco e arquivo não compartilham uma transação atômica.

Aprendizado fica separado em contexto/aprendizados.md e no SQLite. Observações
candidatas aparecem durante o uso; regras inferidas exigem revisão explícita antes
da ativação. Para geração contextual, generation-context aceita campaign_id,
account_id, contact_id opcional, task e plan_step_id opcional; para email use o passo
alvo, preservando objetivo/abordagem/variante. Não compartilhar ou transmitir dados.

# Rotina de acompanhamento

A preferência pode ser manual, agendada ou combinada. O vendedor escolhe dias,
um ou vários horários, fuso IANA e campanhas. Não existe frequência padrão já
ativada. A criação depende de revisão da programação, consulta manual inicial,
armazenamento acessível e executor nativo comprovados.

Preview usa a primeira ocorrência de horário repetido em mudança de fuso. Horário
inexistente passa ao primeiro instante válido do mesmo dia; colisões contam uma
vez. Mostrar essa regra sem expor RRULE ou pedir que o vendedor edite arquivos.

## Instrução durável da tarefa

Executar a skill `replies` com origem `scheduled` e os identificadores de Scope,
diretório persistente e campanhas vinculados à tarefa pelo adaptador confiável.
Adquirir lease antes de bootstrap, recuperar histórico e reconciliar ações incertas.
Consultar somente contas e conversas acompanhadas; salvar eventos e cursores de
cada fonte atomicamente. Falha parcial preserva o último cursor bem-sucedido.

Preparar sugestões e próximas ações para revisão. Não enviar mensagens, escrever
CRM ou realizar enriquecimento pago implicitamente. Respostas pausam os contatos;
interesse/reunião pausa a conta e pedido de não contato bloqueia imediatamente.

Notificar somente mudança relevante, ação necessária ou falha ainda não reportada.
Sem mudança acionável, ficar em silêncio. Não repetir aviso por novo horário de
consulta. A consulta manual sempre apresenta horário e cobertura.

## Ciclo do scheduler

`schedule-request` exige diagnóstico e mapeamento de parâmetros nativos verificados.
O destino é o mesmo projeto e a mesma pasta: `project_job` para execuções do projeto,
ou `dedicated_chat` para conversa operacional distinta do setup. O host comprova
`target` com `workspace_path`, `project_id` e, para chat dedicado, `chat_id` e
`setup_chat_id` diferentes. Sem destino apropriado, explicar o limite e seguir manual.
`native_configuration` contém `schedule` normalizado, `target` e `parameters` reais
do scheduler. Horários no prompt não comprovam correspondência. Confirmar também
`effective_schedule`, destino, `confirmed_at` e as três `next_occurrences` efetivas
na resposta nativa; divergências mantêm reconciliação pendente e retêm o ID real.
Rotinas legadas sem destino comprovado ficam bloqueadas na entrada scheduled;
a consulta manual continua disponível. `schedule-request` com o destino e configuração
revisados persiste awaiting_native_confirmation/reconciliation_required e retorna
operation=reconcile, request_id e o native_id existente. O host consulta/adapta essa
mesma rotina por ID e registra o resultado com `schedule-record-result`; não chama
create. A confirmação precisa do mesmo native_id, target, effective_schedule,
confirmed_at e next_occurrences compatíveis para adotar/reativar. Para interromper
essa rotina, usar `schedule-request` com active=false, o mesmo executor/tool e a
configuração nativa de pausa; operation=pause conserva o ID. Registrar a confirmação
nativa da pausa (next_occurrences=[]). Nenhuma dessas intenções afirma efeito externo
antes da confirmação; estado/diagnósticos anteriores são preservados para revisão.
Só retorna uma intenção; não cria tarefa externa. Após a confirmação do vendedor,
o host chama seu scheduler oficial e registra o resultado com
`schedule-record-result`. Nenhum ID externo é inventado. Se a criação ou edição
ficar incerta, consultar o scheduler antes de repetir. Pausa/edição usa o ID real
existente e respeita o executor/instância de origem. Sem scheduler, orientar e
manter conferência manual; sem estado durável, não prometer rotina recuperável.

---
name: check-connections
description: Descubra ferramentas e verifique capacidades sem presumir autenticação ou custo. Use após configuração, troca de conta ou falha de conexão.
---

# Verificar conexões

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

Entrar por `resume` com a instância da pasta privada resolvida. Consultar perfil,
`../../references/connectors.md`, catálogo e bindings. Não ler arquivos de credenciais.

1. Inventariar ferramentas nativas e recursos de descoberta de ferramentas
   diferidas/plugins. Registrar cobertura: visibilidade incompleta significa
   `unknown`, não ausência do serviço. Reaproveitar conexões existentes.
   Incluir todas as ferramentas citadas pelo vendedor em `connections-checklist`,
   passando o catálogo atual; persistir status e próximo passo com
   `connections-step`. Uma desconhecida exige confirmar produto/site e
   pesquisa guiada da documentação e catálogo nativo, sem desaparecer da lista.
   Cortex exige confirmar qual produto é; não inferir capacidades pelo nome.
2. Associar operação normalizada a nome real e identidade opaca da conexão.
   Enviar `connections-discover` com custo evidenciado ou `unknown`. Nome listado
   não comprova autenticação nem permissão. Uma troca de conta cria outra geração
   lógica e invalida capacidades/propostas antigas.
3. Antes de testar, revisar operação/custo. `connections-prepare-probe` recebe
   capability completo e exato retornado por `connections-discover`; o runtime
   compara com o binding atual salvo, incluindo custo, ferramenta e geração.
   Retorna somente um intent local, sem executar fornecedor, autenticar ou verificar
   a conexão. Não altere campos para tentar satisfazer o gate. Permite apenas
   leitura gratuita conhecida. Busca de empresa pode consumir créditos: se paga ou custo
   desconhecido, seguir a ponte normal de proposta/custo/aprovação. Nunca revelar
   dados, criar registros, rascunhos ou enviar para testar conexão.
4. O host executa leitura mínima e passa status, conexão e referência de evidência
   redigida a `connections-record-probe`. Associar identidade à conta/usuário;
   2xx sem identidade comprovada na resposta ou sem evidência mantém declarado;
   o valor apenas declarado no inventário não serve como comprovação. Identidade
   divergente é erro de conexão. 401:
   autenticação falhou; 403: permissão insuficiente. Não salvar resposta privada
   bruta nem afirmar que leitura verificada comprova escrita ou envio.
5. Para reconectar, orientar login nativo com a fonte oficial verificada do catálogo
   e mencionar administrador quando aplicável. Sem link atual confiável, usar o
   catálogo nativo ou informar que a orientação precisa ser verificada. Não inventar
   URLs/servidores MCP. Não pedir segredos nem instalar automaticamente.
6. Após login, redescobrir e repetir só o teste permitido. Sem acesso, permitir
   etapas independentes e explicar o impacto no trabalho pretendido.
   Recalcular checklist após cada descoberta/probe. Conhecido, suporte documentado,
   instalado, habilitado, tools descobertas e autenticado são estados distintos.
   Listar leitura, escrita, draft, envio, calendário e custos separadamente.
   SMTP sozinho permite envio, não leitura de respostas/enviados. No NetSuite,
   distinguir conta comercial, NSCORP, demo/produção, usuário e role; confirmar
   significado dos campos com o vendedor. Conectar o CRM escolhido sem recomendar
   migração. Bloqueio administrativo deve ter tarefa concreta e continuar visível.

Relatar no idioma do vendedor, por operação: visibilidade, autenticação, permissão,
verificação, custo e próximo passo. Separar testes não executados de falhas. Acesso
real a cada fornecedor/superfície exige evidência própria; um fixture não prova
integração. Não afirmar que o runtime intercepta chamadas feitas fora da ponte.

Resolver primeiro a instância local conforme `../../references/workspace-protocol.md`.
Se existir marcador inválido ou banco ausente, recuperar essa instância; não usar
outra configuração global. Descoberta de ferramentas continua nativa e por capacidade.

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
3. Antes de testar, revisar operação/custo e a assinatura da ferramenta real.
   `connections-prepare-probe` recebe o capability completo/exato retornado por
   `connections-discover` e `native_input` com os argumentos nativos reais dessa
   leitura mínima. O runtime compara o binding atual salvo, incluindo custo e
   geração, e persiste uma permissão de leitura gratuita de uso único, consumida
   pelo PreToolUse. O comando não executa o fornecedor nem autentica a conta.
   Não altere capability/custo para passar no gate. Não usar escrita, reveal,
   criação de draft ou envio como probe. Execute a ferramenta real com os mesmos
   argumentos preparados; se a chamada for negada, resolva o motivo, sem desativar
   hook, permissão ou mudar argumentos fora da ponte.
4. Depois do retorno real, use `connections-record-probe` com identidade, conexão,
   status e referência de evidência redigida. 2xx sem identidade comprovada ou sem
   evidência mantém declarado; identidade do inventário não basta. 401 indica
   falha de autenticação e 403 permissão negada. Não salvar corpus privado.
   Se a leitura gratuita retornou metadados nativos de permissões, registre-os
   nesse resultado e use `connections-verify-permissions` com connection_id,
   evidence_id e response contendo exatamente esses metadados já salvos. Catálogo,
   identidade autenticada de outra operação ou permissões inventadas não servem.
   Sem esses metadados, uma operação visível da conta autenticada pode continuar
   declarada: a primeira execução comercial usa proposta com operation_validation,
   limite explícito e aprovação mesmo se gratuita. Mapear argumentos por
   `proposal-bind-native` antes de aprovar; só sucesso real comprova a operação.
   Uma operação denied/failed não é um teste permitido nem herda acesso da irmã.
5. Para reconectar, orientar login nativo com a fonte oficial verificada do catálogo
   e mencionar administrador quando aplicável. Sem link atual confiável, usar o
   catálogo nativo ou informar que a orientação precisa ser verificada. Não inventar
   URLs/servidores MCP. Não pedir segredos nem instalar automaticamente.
6. Após login, redescobrir e repetir só o teste permitido. Sem acesso, permitir
   orientação/diagnósticos e explicar o impacto, mantendo o bloco pendente.
   Antes de concluir, use `setup-status`: são obrigatórios CRM com leitura,
   fonte de prospecção para empresas/pessoas e comunicação com leitura e recursos
   nativos de draft/envio. CRM somente leitura é aceito; escrita tem gate próprio.
   Nunca testar conexão enviando email, escrevendo CRM ou gastando créditos sem
   consentimento. Falta de ferramenta de prospecção bloqueia a busca; não recorrer
   à web para empresas, pessoas, emails ou caixas genéricas.
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

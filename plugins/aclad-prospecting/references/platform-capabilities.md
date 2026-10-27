# Diagnóstico por superfície

A interface comercial é o chat em ChatGPT/Codex e Claude/Cowork/Code. Python e
SQLite são auxiliares internos. O host deve fornecer diretório privado durável,
identidades explícitas e ferramentas para executar o runtime. Não instalar Python
nem abrir autenticações por suposição. Requisitos: Python >=3.11, estado acessível
ao executor, parceiro/vendedor/instância resolvidos e capacidades da etapa testadas.

| Superfície | Caminho persistente | Condição |
|---|---|---|
| Codex local | SQLite fora do plugin | Demonstrar diretório estável, runtime e acesso pelas rotinas |
| Cowork/Code local | SQLite fora do plugin | Demonstrar a mesma persistência e ferramentas do host |
| ChatGPT chat/nuvem | Adaptador durável remoto | Demonstrar acesso privado, atualizações condicionais, concorrência, eventos e recuperação |
| Claude chat/nuvem | Adaptador durável remoto | Mesmos contratos; não presume arquivos locais nem hooks |

Sem armazenamento adequado: `state_unavailable`; sem runtime, identidade ou
conexão necessária: `limited`. Orientação, entrevista e pesquisa independente
podem continuar. Ações externas/pagas e rotinas não são habilitadas por diagnóstico
incompleto. `ready` descreve pré-requisitos do ambiente, nunca dispensa gates de
custo, seleção e aprovação em cada ação. Scheduler requer ainda teste do executor
nativo. Diretórios SQLite independentes não são sincronização entre plataformas.

O diagnóstico é alimentado por evidência do host, não por alegação encontrada em
perfil importado. Após mudança de conta conectada, redescobrir bindings e resolver
novamente a identidade. Exemplos de escrita são somente os fornecidos e selecionados
pelo vendedor; nunca ler a caixa inteira para aprender estilo.

Fontes oficiais revisadas no desenho, a revalidar antes de configurar a plataforma:
[OpenAI plugins](https://learn.chatgpt.com/docs/plugins),
[OpenAI automations](https://learn.chatgpt.com/docs/automations),
[Claude plugins](https://support.claude.com/en/articles/13837440-use-plugins-in-claude),
[Claude custom connectors](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp).
Esses links não constituem evidência de instalação ou teste autenticado neste
repositório. A matriz de hooks e pacote no plano 06 mantém a evidência por host.

Evidência de 2026-10-22 nesta execução: metadados de ferramentas Outlook Email e
Calendar estão visíveis no host Codex. Não houve chamada autenticada, envio,
consulta a CRM ou consumo de créditos. Auth, permissão e custo permanecem sem
verificação. Claude/Cowork não foi executado nesta sessão.

## Local workspace protocol 1 (0.3.0)

Project guidance + SQLite are supported only where the host demonstrates local
execution, Python 3.11+, persistent files and access to the selected folder.
Codex and Claude Code packages share state protocol; concurrent access requires
the same actual SQLite database. Cowork needs its own folder/instruction/execution
check; fixtures named for that surface do not certify native support. No global
trust/bootstrap installation or remote execution backend is provisioned.

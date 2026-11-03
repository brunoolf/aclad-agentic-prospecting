<picture>
  <source media="(prefers-color-scheme: dark)" srcset="plugins/aclad-prospecting/assets/icon-dark.png">
  <img src="plugins/aclad-prospecting/assets/icon-light.png" alt="ACLAD Prospecting" width="88">
</picture>

# ACLAD Prospecting

Seu assistente de prospecção para parceiros NetSuite. Configure o perfil da empresa, escolha as contas que quer trabalhar e prepare abordagens personalizadas com seu CRM e suas ferramentas.

## Instalar

Escolha o aplicativo que você vai usar.

### Codex

Com o Codex instalado, execute estes dois comandos no terminal:

```sh
codex plugin marketplace add brunoolf/aclad-agentic-prospecting
codex plugin add aclad-prospecting@aclad-latam
```

Depois abra uma conversa nova no Codex. Se o aplicativo pedir confirmação para habilitar o plugin ou seus hooks, revise e confirme na própria tela.

### Claude Code

No Claude Code, execute:

```text
/plugin marketplace add brunoolf/aclad-agentic-prospecting
/plugin install aclad-prospecting@aclad-latam
```

Abra uma conversa nova e use `/aclad-prospecting:setup`.

### Claude Desktop / Cowork

[**Baixar o plugin para Claude**](https://github.com/brunoolf/aclad-agentic-prospecting/releases/latest/download/aclad-prospecting-claude.zip)

1. Baixe o ZIP pelo botão acima, sem extrair.
2. Na área de plugins do aplicativo, escolha a opção de adicionar ou carregar um plugin e selecione o ZIP.
3. Habilite o plugin e abra uma conversa nova no Cowork.

A instalação de plugins precisa estar disponível na sua conta. Anexar o ZIP a uma conversa comum não instala o plugin.

## Começar a usar

1. Crie uma pasta no computador para a sua prospecção.
2. Abra essa pasta como projeto no aplicativo.
3. Envie esta mensagem:

> Configure meu assistente de prospecção com o ACLAD Prospecting.

Se o botão de configuração abrir um chat sem projeto, primeiro escolha ou confirme
sua pasta de prospecção no aplicativo. O assistente ajudará nessa etapa antes de
salvar suas informações.

A configuração avança por blocos: **seu ambiente → você e sua empresa → conexões →
comunicação → acompanhamento → ICPs → primeira campanha**. Cada bloco mostra o que
ficou pronto e o que falta. As perguntas usam seleção interativa quando o
aplicativo oferece esse recurso; caso contrário, aparecem uma de cada vez no chat.

Para começar a prospectar, conecte **um CRM, uma ferramenta de prospecção e uma de
comunicação**. CRM somente leitura é aceito; gravações ficam bloqueadas quando não
há permissão de escrita. Faça login somente pelo fluxo do aplicativo; nunca envie
senha ou chave de API na conversa.

Você pode manter vários ICPs nomeados e acompanhar campanhas separadas. A primeira
lista mostra nome e website: você escolhe as empresas antes do enriquecimento e
dos contatos. Os emails são preparados como rascunhos na ferramenta conectada,
para sua revisão antes de enviar. Se escolher acompanhamento automático, confira
no resumo final se a rotina foi realmente ativada.

Depois, você pode pedir:

- “Monte meus ICPs usando os clientes do CRM.”
- “Encontre contas que combinam com este perfil.”
- “Prepare uma abordagem personalizada para estas empresas.”
- “Confira as respostas das campanhas que estou trabalhando.”

**Enriquecimento pago, gravação no CRM e envio de emails precisam da sua aprovação.**

## Atualizar o plugin

Atualize o marketplace/plugin pela área de plugins do aplicativo. No Cowork, baixe
o ZIP atual pelo link acima e use a opção de atualizar/substituir o plugin. Depois
abra uma conversa nova na **mesma pasta** e peça para retomar a configuração.
Preserve sua pasta de prospecção; não apague nem copie o banco para outro vendedor.

## Continuar em outro dia

Abra a mesma pasta e peça:

> Retome minha prospecção e mostre o que está pendente.

Mantenha essa pasta privada. Ela guarda seu contexto, suas preferências e o histórico do trabalho. Para atualizar o plugin, preserve a pasta no mesmo lugar; não copie o banco entre vendedores.

## Antes do primeiro teste

Use Codex, Claude Code ou Cowork com acesso a uma pasta local e execução de ferramentas. O assistente confere os recursos necessários no início. O ChatGPT comum no navegador não deve ser tratado como uma instalação local deste plugin.

As ferramentas de CRM, prospecção, email e calendário dependem das conexões e permissões disponíveis na conta de cada pessoa. Instalar o plugin não conecta essas contas automaticamente.

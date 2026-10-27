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

O assistente vai perguntar sobre sua empresa e seu site, ajudar com as ferramentas disponíveis e preparar os perfis de cliente e o estilo de escrita para sua revisão. Faça login nas ferramentas somente pelo fluxo do aplicativo, quando você decidir conectá-las.

Depois, você pode pedir:

- “Monte meus ICPs usando os clientes do CRM.”
- “Encontre contas que combinam com este perfil.”
- “Prepare uma abordagem personalizada para estas empresas.”
- “Confira as respostas das campanhas que estou trabalhando.”

**Enriquecimento pago, gravação no CRM e envio de emails precisam da sua aprovação.**

## Continuar em outro dia

Abra a mesma pasta e peça:

> Retome minha prospecção e mostre o que está pendente.

Mantenha essa pasta privada. Ela guarda seu contexto, suas preferências e o histórico do trabalho. Para atualizar o plugin, preserve a pasta no mesmo lugar; não copie o banco entre vendedores.

## Antes do primeiro teste

Use Codex, Claude Code ou Cowork com acesso a uma pasta local e execução de ferramentas. O assistente confere os recursos necessários no início. O ChatGPT comum no navegador não deve ser tratado como uma instalação local deste plugin.

As ferramentas de CRM, prospecção, email e calendário dependem das conexões e permissões disponíveis na conta de cada pessoa. Instalar o plugin não conecta essas contas automaticamente.

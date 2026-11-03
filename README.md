<picture>
  <source media="(prefers-color-scheme: dark)" srcset="plugins/aclad-prospecting/assets/icon-dark.png">
  <img src="plugins/aclad-prospecting/assets/icon-light.png" alt="ACLAD Prospecting" width="88">
</picture>

# ACLAD Prospecting

Seu assistente de prospecção para parceiros NetSuite. Configure o perfil da empresa, escolha as contas que quer trabalhar e prepare abordagens personalizadas com seu CRM e suas ferramentas.

## Instalar

Escolha o aplicativo que você vai usar.

Link do marketplace: [brunoolf/aclad-agentic-prospecting](https://github.com/brunoolf/aclad-agentic-prospecting).

### Codex

1. Abra a área **Plugins** do Codex e escolha **Adicionar marketplace**.
2. Cole `https://github.com/brunoolf/aclad-agentic-prospecting` e adicione.
3. No catálogo ACLAD, escolha **ACLAD Prospecting**, instale e habilite.
4. Revise as confirmações de permissões e hooks na própria tela.

Se preferir instalar pelo terminal, com o Codex instalado:

```sh
codex plugin marketplace add brunoolf/aclad-agentic-prospecting
codex plugin add aclad-prospecting@aclad-latam
```

Depois siga **Começar a usar**, abaixo, para criar sua pasta e abrir o setup nela.

### Claude Code

No Claude Code, execute:

```text
/plugin marketplace add brunoolf/aclad-agentic-prospecting
/plugin install aclad-prospecting@aclad-latam
```

Revise a instalação e depois siga **Começar a usar**, abaixo.

### Claude Desktop / Cowork

1. Abra a aba **Cowork** e depois **Personalizar / Customize → Plugins**.
2. Escolha **Adicionar / Add → Adicionar marketplace**.
3. Escolha adicionar por repositório e cole `https://github.com/brunoolf/aclad-agentic-prospecting`.
4. Adicione o marketplace, escolha **ACLAD Prospecting** no catálogo e habilite o plugin.

Os nomes dos menus podem variar com o idioma e a versão. Se a organização
restringir marketplaces, peça ao administrador para liberar esse repositório.

## Começar a usar

1. Crie uma pasta privada no computador, por exemplo **Prospecção — Minha empresa**.
2. No Codex ou Claude Code, abra/adicione essa pasta como projeto. No Cowork,
   selecione essa pasta e conceda o acesso solicitado.
3. Abra um **novo chat ou tarefa nessa pasta**, com o plugin habilitado.
4. Cole o comando de setup do seu aplicativo:

**Codex** — confirme a habilidade de setup se o seletor aparecer:

```text
$aclad-prospecting:setup
```

**Claude Code / Cowork:**

```text
/aclad-prospecting:setup
```

5. Confirme a pasta quando o assistente perguntar e siga a configuração por blocos.

Se o atalho não aparecer, confira se o plugin está habilitado e abra uma conversa
nova. No Codex, digite `$` e selecione a habilidade `aclad-prospecting:setup`.

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
configuração pergunta as **indústrias/setores** e as **subindústrias/segmentos**
que você quer trabalhar. Confirme cada recorte antes de aprovar o ICP; também é
possível escolher explicitamente não limitar por indústria ou subindústria. A primeira
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

Atualize o marketplace e o plugin pela área de plugins do aplicativo. Depois
abra uma conversa nova na **mesma pasta** e peça para retomar a configuração.
Preserve sua pasta de prospecção; não apague nem copie o banco para outro vendedor.

## Continuar em outro dia

Abra a mesma pasta e peça:

> Retome minha prospecção e mostre o que está pendente.

Mantenha essa pasta privada. Ela guarda seu contexto, suas preferências e o histórico do trabalho. Para atualizar o plugin, preserve a pasta no mesmo lugar; não copie o banco entre vendedores.

## Antes do primeiro teste

Use Codex, Claude Code ou Cowork com acesso a uma pasta local e execução de ferramentas. O assistente confere os recursos necessários no início. O ChatGPT comum no navegador não deve ser tratado como uma instalação local deste plugin.

As ferramentas de CRM, prospecção, email e calendário dependem das conexões e permissões disponíveis na conta de cada pessoa. Instalar o plugin não conecta essas contas automaticamente.

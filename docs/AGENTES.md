# Conectando um agente de IA

Por padrão o `docserver` fala [MCP](https://modelcontextprotocol.io) via
**stdio**: o cliente sobe o processo `docserver serve` diretamente, sem
porta nem rede. Isso significa que o cliente precisa rodar na mesma máquina
(ou container) onde `docs-fonte/`, `docs-normalizado/` e `data/indice.db`
existem — e também que não existe um link para "abrir" ou compartilhar: o
processo só fala pelos streams padrão de entrada/saída de quem o subiu.

## Atalho: `docserver server-mcp --local`

O jeito mais simples de servir via HTTP na rede local:

```bash
docserver server-mcp --local
```

Usa sempre o `data/indice.db` e o `docs-normalizado/` do próprio projeto
(independente do diretório de onde o comando roda), sobe em
`0.0.0.0:8765` e imprime a URL de acesso (`http://<IP-da-máquina>:8765/mcp`).
Sem `--local`, sobe em `127.0.0.1:8765` (só esta máquina acessa). Se o índice
não existir, aborta pedindo `docserver ingest`. Para host, porta ou caminhos
diferentes, use `serve --http` como descrito abaixo.

## `serve --http` (configuração manual)

Se você precisa de um link (para um cliente MCP remoto, para testar com
`curl`/[MCP Inspector](https://github.com/modelcontextprotocol/inspector),
ou para servir mais de um cliente ao mesmo tempo), suba com `--http`:

```bash
docserver --indice /caminho/absoluto/data/indice.db \
  --docs-normalizado /caminho/absoluto/docs-normalizado \
  serve --http --host 127.0.0.1 --porta 8765
```

O endpoint fica em `http://127.0.0.1:8765/mcp`. Por padrão o bind é em
`127.0.0.1` (só a própria máquina acessa) — mude `--host` para `0.0.0.0`
apenas se precisar expor para a rede, e nesse caso considere colocar atrás
de um proxy com autenticação, já que o `docserver` não implementa nenhuma
(ver "Fase futura" em `docs/ARQUITETURA.md`). Use `--http` só quando
precisar de fato de rede; para o caso comum (um cliente MCP local) stdio
continua mais simples e não exige gerenciar porta nem processo em segundo
plano.

> Os caminhos exatos dos arquivos de configuração de cada cliente mudam com
> frequência — confira sempre a documentação oficial do cliente que você
> está usando. Os exemplos abaixo mostram o formato do bloco de configuração,
> não necessariamente o arquivo/local mais atual.

> **Sempre passe caminhos absolutos.** O cliente MCP sobe o processo no
> diretório que ele escolher (o Claude Desktop, por exemplo, não usa a pasta
> do projeto e ignora uma chave `cwd`). Sem `--indice` e `--docs-normalizado`
> absolutos, o servidor procura `data/indice.db` e `docs-normalizado/`
> relativos a esse diretório e não encontra nada. As opções globais vêm
> **antes** do subcomando `serve`.

## Claude Desktop

Em `claude_desktop_config.json` (Windows: `%APPDATA%\Claude\`; macOS:
`~/Library/Application Support/Claude/`):

```json
{
  "mcpServers": {
    "docserver": {
      "command": "/caminho/absoluto/para/o/projeto/.venv/bin/docserver",
      "args": [
        "--docs-normalizado", "/caminho/absoluto/para/o/projeto/docs-normalizado",
        "--indice", "/caminho/absoluto/para/o/projeto/data/indice.db",
        "serve"
      ]
    }
  }
}
```

No Windows, o binário do venv é `.venv\Scripts\docserver.exe` (escape as
barras no JSON: `"D:\\projeto\\.venv\\Scripts\\docserver.exe"`). Reinicie o
Claude Desktop depois de editar o arquivo.

## Claude Code

```bash
claude mcp add docserver -- /caminho/absoluto/.venv/bin/docserver   --docs-normalizado /caminho/absoluto/docs-normalizado   --indice /caminho/absoluto/data/indice.db   serve
```

Use o binário do venv: `docserver` só está no `PATH` com o venv ativado, e o
Claude Code não o ativa. Depois, confira com `/mcp` dentro do Claude Code.

## VS Code / GitHub Copilot

No `.vscode/mcp.json` do workspace:

```json
{
  "servers": {
    "docserver": {
      "command": "docserver",
      "args": ["serve"]
    }
  }
}
```

## Cursor

No `.cursor/mcp.json` (ou na configuração global de MCP do Cursor):

```json
{
  "mcpServers": {
    "docserver": {
      "command": "docserver",
      "args": ["serve"]
    }
  }
}
```

## Conectando de outra máquina na rede

Os exemplos acima sobem o servidor via stdio, na mesma máquina do cliente.
Para consumir de outro PC (mesma rede local), suba com `--http --host
0.0.0.0` na máquina que tem `docs-fonte/`, `docs-normalizado/` e
`data/indice.db`:

```bash
docserver server-mcp --local
```

`--host 0.0.0.0` é o que aceita conexões de outras máquinas — com o padrão
(`127.0.0.1`) só o próprio PC acessa, mesmo com a porta liberada no
firewall.

1. **Descubra o IP dessa máquina na rede** (Windows: `ipconfig`; Linux/macOS:
   `ip addr` ou `ifconfig`) — algo como `192.168.x.x`.
2. **Libere a porta no firewall**, como administrador. No Windows:
   ```powershell
   New-NetFirewallRule -DisplayName "docserver MCP (8765)" -Direction Inbound `
     -Protocol TCP -LocalPort 8765 -Action Allow -Profile Private
   ```
   `-Profile Private` restringe a liberação a redes marcadas como
   privadas (doméstica/trabalho) no Windows — não libera em redes públicas.
3. **No outro PC**, teste que a rede enxerga antes de configurar o cliente:
   ```bash
   curl http://192.168.x.x:8765/mcp
   ```
4. **Configure o cliente com a URL** em vez de um comando local:

   VS Code / Copilot (`.vscode/mcp.json`):
   ```json
   {
     "servers": {
       "docserver": {
         "type": "http",
         "url": "http://192.168.x.x:8765/mcp"
       }
     }
   }
   ```

   Claude Code:
   ```bash
   claude mcp add --transport http docserver http://192.168.x.x:8765/mcp
   ```

   Claude Desktop: hoje servidor remoto se adiciona pela UI (Settings →
   Connectors), não editando `claude_desktop_config.json` diretamente.

**Sem autenticação nenhuma** — qualquer dispositivo que alcance
`IP:porta` nessa rede consegue ler e buscar toda a documentação indexada.
Aceitável numa rede doméstica ou de escritório confiável; nunca exponha isso
direto na internet (nada de port-forward no roteador) sem colocar atrás de
um proxy com autenticação antes (ver "Fase futura" em
`docs/ARQUITETURA.md`). Se a máquina usa IP dinâmico (DHCP), o endereço pode
mudar a cada reinício — configure IP fixo se isso incomodar.

## As três ferramentas (tools)

| Tool | Quando o agente deve chamar |
|---|---|
| `listar_documentos()` | Não sabe o que existe na documentação, ou uma busca não retornou nada útil. |
| `buscar(consulta, limite=5, documento=None)` | Antes de responder qualquer pergunta sobre o projeto — sempre, em vez de responder de memória. |
| `ler_documento(caminho)` | O trecho de `buscar` não trouxe contexto suficiente. |

Todas retornam **texto legível**, nunca JSON cru — pensado para ser lido
diretamente pelo agente e citado ao usuário, sempre com o caminho de origem.

**`documento`** restringe a busca a um único arquivo (caminho completo, parcial
ou só o nome) — use quando já se sabe, por `listar_documentos` ou por uma
busca anterior, qual documento tem a resposta. Evita que trechos de *outros*
documentos indexados se misturem no resultado só porque bateram bem no termo
buscado; é a defesa direta contra o índice ter mais de um documento com
vocabulário parecido (dois PDFs institucionais, por exemplo).

`buscar` também aplica um corte mínimo de relevância antes de devolver
resultados: um trecho só entra na resposta se a similaridade vetorial da
consulta com ele for alta o bastante, ou se ele casou de fato na busca por
termo exato (BM25) com algum termo relevante da pergunta. Uma resposta vazia
é intencional — significa que
nada no índice passou nesse corte — e não deve ser preenchida com uma
resposta "de memória"; oriente o usuário a reformular a pergunta, restringir
por `documento`, ou confirmar se o assunto está mesmo na documentação
indexada.

## Exemplo de `CLAUDE.md`

Adicione ao `CLAUDE.md` (ou equivalente) do projeto que está sendo
documentado, para reforçar o hábito de consultar antes de responder:

```markdown
## Documentação do projeto

Este projeto tem um servidor MCP de documentação (`docserver`) conectado.
Antes de responder qualquer pergunta sobre arquitetura, endpoints, variáveis
de ambiente, processos internos ou decisões de projeto, use a ferramenta
`buscar` para consultar a documentação real — não responda de memória.
Se a busca não trouxer nada útil, tente `listar_documentos` para ver o que
existe, ou reformule a consulta (termo técnico exato vs. linguagem natural).
```

## Conhecimento revisado: o fluxo de documentação

Além de servir a documentação que você já tem, o docserver pode **acumular o que
os agentes aprendem** trabalhando num projeto: eles registram decisões e
armadilhas, um revisor aprova ou rejeita, e o que passa volta para os próprios
agentes pela tool `buscar`. O porquê do desenho (e o que ele não promete) está no
ADR "Conhecimento revisado, não código" em `docs/ARQUITETURA.md`; esta seção é o
guia de uso. Regra de ouro: documenta-se só o que **não dá para tirar do código**
(o porquê, a armadilha, a convenção, a operação), nunca "este módulo faz X".

### `docserver init`

Na raiz do projeto:

```bash
docserver init                              # usa o diretório atual
docserver init --raiz /caminho/do/projeto   # outra raiz
docserver init --modelo-revisor <modelo>    # modelo gravado em [revisor].modelo (padrão: claude-sonnet-5-5)
```

Gera o que falta e imprime uma linha por item (`criado ...`, `anexado ...`,
`já existia: ...`). É idempotente e nunca sobrescreve conteúdo seu:

- `.docserver.toml` com os padrões do projeto (`fonte = "docs"`, índice e
  normalizados em `.docserver/`, `embeddings = false`, `ignorar` para a
  quarentena e a tabela `[revisor]`; ver `docs/INGESTAO.md`);
- `docs/conhecimento/`, `docs/_pendentes/` e `docs/_rejeitados/`, cada uma com um
  `.gitkeep` (a pasta vem de `[docs].fonte` se o `.docserver.toml` já existia);
- a entrada `docserver` no `.mcp.json` (`command: docserver`, `args: ["serve"]`,
  **sem caminhos**: o servidor acha o `.docserver.toml` a partir do diretório em
  que o cliente o sobe, então o cliente deve rodar dentro do projeto, e o
  `docserver` precisa estar no `PATH`). Um `.mcp.json` existente só recebe a
  entrada; se não for JSON válido, o `init` avisa e não mexe;
- o bloco mínimo no `CLAUDE.md`, entre `<!-- docserver:inicio -->` e
  `<!-- docserver:fim -->` (anexado, nunca sobrescreve): busque antes de investigar,
  o código não está indexado, use a skill `documentar`, não edite `conhecimento/`
  direto;
- a skill `.claude/skills/documentar/SKILL.md`;
- a linha `.docserver/` no `.gitignore` (o índice e os normalizados são
  regeneráveis; o `docs/` vai para o git).

### Como o agente documenta

Pela skill `documentar` (texto-fonte em `src/docserver/modelos/skill-documentar.md`),
carregada só quando o agente vai registrar algo. O agente:

1. chama `buscar` antes de escrever; se já existe um documento sobre o assunto,
   escreve a nova versão e acrescenta `substitui:`, em vez de duplicar;
2. escreve sempre em `docs/_pendentes/<slug-curto>.md`, direto na pasta (o revisor
   lê os `*.md` do primeiro nível; subpastas não são revisadas), nunca em
   `conhecimento/`;
3. preenche o front matter, em formato plano `chave: valor`:

```markdown
---
titulo: Por que a ingestão usa WAL
tipo: decisao
gerado_por: claude-opus-5-5
commit: a0ecf9e
arquivos: src/docserver/index.py, docs/ARQUITETURA.md
---

# Por que a ingestão usa WAL
...
```

| Chave | Obrigatória | Para quê |
|---|---|---|
| `titulo` | sim | Título curto; também alimenta a busca de documentos parecidos. |
| `tipo` | sim | `decisao`, `armadilha`, `convencao` ou `operacao`. |
| `gerado_por` | sim | Id do modelo do autor; é comparado com o do revisor (ver "Aviso de mesmo modelo"). |
| `commit` | não | Saída de `git rev-parse --short HEAD`; o revisor vê o `git diff <commit>..HEAD` dos `arquivos`. |
| `arquivos` | não | Código a que o documento se refere, separado por vírgula; o revisor confere as afirmações lendo esses arquivos. |
| `substitui` | não | `conhecimento/<arquivo>.md`: o pendente é uma nova versão de um aprovado, que será sobrescrito. |

Corpo: um título `#` e poucas linhas (a skill pede no máximo ~30), sem segredos.

### Como a revisão roda

**Automática**, com o watcher. `docserver watch` num projeto com `.docserver.toml`
também revisa: um `.md` que aparece (criado, modificado ou movido para) em
`_pendentes/` dispara a revisão depois de 10 s sem novos eventos (o agente costuma
escrever e depois editar), e o que já estiver pendente ao subir é revisado logo
após a ingestão inicial. Aprovar move o arquivo para `conhecimento/`, e esse
evento dispara a ingestão pelo caminho normal do watcher. `docserver watch
--sem-revisao` desliga isso (o watcher segue só ingerindo).

**Manual**:

```bash
docserver revisar                     # revisa todos os pendentes e ingere os aprovados
docserver revisar --modelo <modelo>   # outro modelo só nesta execução
docserver revisar --sem-ingestao      # não ingere depois de aprovar
```

`--modelo` substitui `[revisor].modelo`, e vale para o `{modelo}` do comando.
O resumo mostra uma linha por documento (`aprovar`, `ajustar`, `rejeitar` ou
`erro`) com o destino e os motivos. Código de saída: **0** sem erros, **1** se algum
documento deu `erro` ou se outra revisão já está em andamento (o watcher ou
outro terminal: há um lock de revisão), **2** sem `.docserver.toml`.

### O que cada decisão faz

| Decisão | Arquivo | Front matter |
|---|---|---|
| `aprovar` | Vai para `conhecimento/<mesmo nome>` (ou sobrescreve o alvo de `substitui`); o pendente é apagado. | Saem `motivos_rejeicao`, `substitui` e `tentativas`; entram `revisado_por`, `revisado_em` e `parecer` (os motivos do revisor). |
| `ajustar` | Igual a aprovar, mas o corpo é o texto corrigido que o revisor devolveu. | Igual a aprovar; o diff autor-revisor fica no registro. |
| `rejeitar` | Vai para `_rejeitados/<mesmo nome>`. | Entram `motivos_rejeicao`, `tentativas` (+1), `revisado_por` e `revisado_em`. |
| `erro` | Continua em `_pendentes/`. | Intocado; **não** gasta tentativa. |

Rejeitado, o autor lê `motivos_rejeicao`, corrige e move o arquivo de volta para
`_pendentes/`. `erro` é qualquer falha do revisor (saída que não é um JSON de
decisão válido, tempo esgotado, código de saída diferente de zero, ou um texto
ajustado que contém segredo): o documento não é indexado e será revisado de novo
na próxima execução.

### Registro `_revisoes.jsonl`

Cada decisão (inclusive `erro` e as rejeições por checagem) acrescenta uma linha
JSON a `docs/_revisoes.jsonl`, que vai para o git: `documento`, `destino`,
`decisao`, `modelo`, `gerado_por`, `motivos`, `revisado_em`, `sha256` do arquivo
final, `custo_usd` (quando o revisor informa), `aviso` e, em `ajustar`, `diff`.
É a trilha de quem aprovou o quê. O arquivo é ignorado pela ingestão.

### Checagens baratas (sem LLM)

Antes de chamar o revisor, e sem custo, o documento é rejeitado (com
`revisado_por: checagem-automatica`) se:

- não tem front matter, ou falta `titulo`, `tipo` ou `gerado_por`;
- `tipo` não é um dos quatro valores;
- o corpo está vazio;
- há um segredo aparente (token `ghp_`/`github_pat_`/`sk-`, chave `AKIA...` ou chave
  privada);
- `tentativas` já chegou a `max_tentativas`: `limite de tentativas atingido;
  revisão humana necessária`;
- `substitui` aponta para fora de `conhecimento/` ou para arquivo inexistente;
- sem `substitui`, já existe `conhecimento/<mesmo nome>` (a mensagem diz para usar
  `substitui`).

### Limite de tentativas

Cada rejeição soma 1 em `tentativas`. Com `[revisor].max_tentativas` (padrão 3)
atingido, o documento deixa de ir ao revisor: é rejeitado de novo pela checagem
automática, e a decisão passa a ser humana (corrigir a causa de fundo ou descartar
o arquivo).

### Aviso de mesmo modelo

Se `gerado_por` é igual ao modelo do revisor (comparação exata, sem diferenciar
maiúsculas nem espaços), a revisão **segue**, mas imprime `[aviso] ...` e grava o
`aviso` no registro: um LLM tende a aprovar texto do próprio modelo. Use um modelo
diferente do que escreve, ou melhor, de outra família.

### Trocar o revisor

O revisor é o `[revisor].comando` do `.docserver.toml`, e o padrão é:

```toml
[revisor]
comando = ["claude", "-p", "--model", "{modelo}", "--output-format", "json", "--allowedTools", "Read,Grep,Glob", "--strict-mcp-config"]
modelo = "claude-sonnet-5-5"
# timeout_s = 600    # opcional: segundos até desistir de uma revisão (padrão 600)
```

Contrato para qualquer comando (outra família de modelos, um script seu):

- `{modelo}`, em qualquer item da lista, é trocado pelo modelo (`modelo` ou
  `--modelo`);
- o **prompt chega pelo stdin** (documento, versão atual se há `substitui`,
  aprovados parecidos, `git diff`, checklist), não por argumento, porque não cabe
  na linha de comando do Windows. O processo roda na raiz do projeto, e o
  executável é resolvido pelo `PATH` (`claude.cmd` incluído);
- o texto do documento vai entre delimitadores com um hash do conteúdo, e o prompt
  manda tratá-lo como dado, não como instrução;
- a resposta, no stdout, é um objeto JSON:

```json
{"decisao": "aprovar", "motivos": ["conferido em index.py"], "texto": "só em ajustar"}
```

  `decisao` é `aprovar`, `ajustar` ou `rejeitar`; `motivos` é uma lista de textos;
  `texto` é o corpo Markdown completo e corrigido, sem front matter, e é obrigatório
  em `ajustar`;
- o parse é tolerante: aceita o JSON puro, dentro de um bloco de código `json`, ou
  como o primeiro objeto `{...}` no meio de texto;
- o envelope do `claude -p --output-format json` também é aceito: o objeto com o
  campo `result` (texto com a decisão) e o `total_cost_usd`, que vira `custo_usd`
  no registro;
- código de saída diferente de zero, tempo esgotado (`timeout_s`) ou resposta sem
  decisão válida = `erro` (o documento fica em `_pendentes/`).

Exemplo com um script próprio, que lê o prompt do stdin e chama outro modelo:

```toml
[revisor]
comando = ["python", "ferramentas/revisor_externo.py", "{modelo}"]
modelo = "<modelo-de-outra-familia>"
```

As pastas (`pendentes`, `aprovados`, `rejeitados`, relativas a `[docs].fonte`) e o
`registro` também são configuráveis na tabela `[revisor]`.

### No ambiente isolado

O repositório `claude-isolado` roda o Claude Code num container e já sabe subir
este fluxo; veja a seção "Projeto com RAG" do README dele
(`D:\TI\Claude Code - Isolado\README.md`). Em resumo:

- `-Repo <url>` (`--repo` no bash) clona o projeto num volume
  `claude-isolado-repo-<nome>`, montado em `/workspace`, só na primeira vez;
- se o projeto tem `.docserver.toml`, o entrypoint sobe `docserver watch` em
  segundo plano (log em `/workspace/.docserver/watch.log`), então a ingestão
  inicial e a revisão automática funcionam sem comando manual (não sobe em modo
  somente leitura);
- o volume é Linux, o que faz o inotify do watcher funcionar (coisa que um bind
  mount do Windows não garante, ver `docs/INGESTAO.md`);
- `GH_TOKEN` (`-EnvVar GH_TOKEN=...`) permite clonar repositório privado; para
  `git push` de dentro do container é preciso configurar um credential helper.

### Como medir se está valendo a pena

A economia de tokens é plausível, mas **não está comprovada**. O harness em
`avaliacao/tokens/` roda as mesmas tarefas com e sem o MCP docserver e compara
custo e taxa de sucesso; o critério e o passo a passo estão em
[`avaliacao/tokens/README.md`](../avaliacao/tokens/README.md). Meça uma linha de
base logo no início e repita semanas depois, com mais conhecimento acumulado: o
mecanismo se mantém se o custo médio cair sem cair a taxa de sucesso.

# Ingestão

## Como adicionar documentos

Copie (ou mova) os arquivos para `docs-fonte/`, em qualquer estrutura de
pastas — ela é espelhada em `docs-normalizado/`. Depois rode:

```bash
docserver ingest
```

O comando reindexa **tudo** do zero a cada execução: não existe indexação
incremental (ver `docs/ARQUITETURA.md`). Rode de novo sempre que adicionar,
editar ou remover arquivos em `docs-fonte/`, ou deixe `docserver watch`
fazendo isso sozinho (ver "Ingestão automática" abaixo).

**Remover um arquivo de `docs-fonte/` e rodar `docserver ingest` já basta** —
a ingestão apaga automaticamente o `.md` correspondente em
`docs-normalizado/` (e o retira do índice) quando a fonte original não existe
mais, listado como "Removidos" no relatório. Isso existe para não deixar
documentação obsoleta sendo servida por `ler_documento` ou aparecendo em
`listar_documentos` — foi exatamente um `.md` órfão desses (de um PDF já
apagado de `docs-fonte/`, indexado numa ingestão anterior) que causou uma
busca sobre um documento misturar trechos de outro completamente diferente.

Flags úteis:

```bash
docserver ingest --limpar           # remove os .md gerados pelo docserver e esvazia o índice antes de reingerir
docserver ingest --sem-embeddings   # pula a camada vetorial — ingestão bem mais rápida em dev
docserver ingest --forcar           # permite esvaziar o índice (ver "Proteções contra perda de dados")
```

### Nomes dos arquivos normalizados

Um `.md` de origem mantém o nome; qualquer outro formato ganha `.md` **depois**
da extensão original: `docs-fonte/api/contratos.md` → `docs-normalizado/api/contratos.md`,
`docs-fonte/manual.pdf` → `docs-normalizado/manual.pdf.md`. Assim `manual.pdf`,
`manual.docx` e `manual.md` na mesma pasta viram três documentos distintos, em
vez de um sobrescrever o outro.

O índice guarda o caminho normalizado **relativo a `docs-normalizado/`** e em
formato POSIX (`api/contratos.md`), então ingestão e servidor podem rodar de
diretórios — ou sistemas operacionais — diferentes.

> Índices criados antes dessa mudança guardavam outro formato de caminho e
> outros nomes de arquivo: rode `docserver ingest` uma vez após atualizar. Os
> `.md` antigos gerados pelo docserver são removidos automaticamente como órfãos.

### Proteções contra perda de dados

A ingestão aborta **sem alterar nada** (código de saída 1, mensagem em stderr) quando:

- `--docs-fonte` não existe — erro de digitação ou comando rodado do diretório
  errado. Essa checagem roda antes do `--limpar` e não é contornável.
- não há nenhum arquivo em formato suportado em `--docs-fonte`;
- a ingestão não gerou nenhum chunk e o índice atual tem conteúdo.

Nos dois últimos casos, `--forcar` confirma que a intenção é mesmo esvaziar o índice.

A remoção de órfãos e o `--limpar` só apagam `.md` gerados pelo docserver
(front matter com `origem:`). Qualquer outro `.md` em `docs-normalizado/` é
mantido e listado como "Preservados" no relatório.

## Ingestão automática (`docserver watch`)

Em vez de rodar `docserver ingest` a cada mudança, deixe um watcher observando
`docs-fonte/` num terminal separado do servidor:

```bash
# terminal 1
docserver server-mcp        # ou docserver serve --http

# terminal 2
docserver watch
```

```text
docserver: ingestão inicial
Ingestão concluída em 4.2s
...
docserver: observando D:\...\docs-fonte (Ctrl+C para sair)
docserver: 3 mudança(s) detectada(s), reingerindo
Ingestão concluída em 3.8s
```

Como funciona:

- **Ingestão inicial.** Ao subir, o watcher roda uma ingestão completa para
  pegar o que mudou enquanto ele estava desligado.
- **Agrupamento.** Copiar uma pasta ou salvar um `.docx` gera dezenas de
  eventos. O watcher espera `--espera` segundos (padrão 2) sem nenhum evento
  novo e roda **uma** ingestão. Mudanças feitas enquanto uma ingestão roda
  disparam outra logo depois.
- **Filtro.** Só contam arquivos que a ingestão leria: extensões da tabela de
  formatos suportados, ignorando ocultos (`.algo`) e temporários do Office
  (`~$algo.docx`). Mudanças em pastas vazias ou em formatos não suportados não
  disparam nada.
- **Mesmo pipeline.** Cada disparo é exatamente um `docserver ingest`
  (reindexação completa, remoção de órfãos e todas as proteções da seção
  anterior). Se uma ingestão aborta ou falha, o erro é registrado e o watcher
  continua observando; a próxima mudança tenta de novo.
- **Embeddings em cache.** O modelo é carregado uma vez no processo do watcher,
  então só a primeira ingestão paga esse custo. Use `docserver watch
  --sem-embeddings` para ingestões só léxicas.
- **Convivência com o servidor.** Os embeddings são calculados antes de abrir o
  índice, e a troca dos chunks acontece numa única transação SQLite: o servidor
  vê o índice antigo ou o novo, nunca um meio-termo. Ingestões simultâneas (o
  watcher, `docserver ingest`, `docserver revisar`) se serializam pelo lock de
  ingestão (ver "Lock de ingestão"), então rodar `docserver ingest` à mão com o
  watcher ativo espera a vez em vez de corromper algo.

Os argumentos globais valem igual ao `ingest`:
`docserver --docs-fonte outra/pasta --indice outro.db watch`.

### Como as mudanças são detectadas

O watcher usa a biblioteca [`watchdog`](https://github.com/gorakhargosh/watchdog),
que não relê a pasta periodicamente: ela assina as notificações nativas do
sistema operacional, então a reação é praticamente imediata e o custo parado é
quase zero.

| Sistema | API usada pelo watchdog |
|---|---|
| Windows | `ReadDirectoryChangesW` |
| Linux | `inotify` |
| macOS | `FSEvents` |

### Limitações conhecidas e trabalho futuro (Linux)

O watcher foi desenvolvido e validado no **Windows**. Em Linux o watchdog usa
`inotify`, que funciona em disco local, mas **não entrega eventos** em alguns
cenários comuns:

- volumes montados no Docker a partir de hosts Windows ou macOS
  (`-v ./docs-fonte:/app/docs-fonte`);
- pastas do Windows acessadas pelo WSL2 (`/mnt/c/...`);
- compartilhamentos de rede (NFS, SMB/CIFS).

Além disso, cada subpasta consome um *watch*, limitado por
`fs.inotify.max_user_watches`. Árvores muito grandes podem estourar o limite
(`sysctl fs.inotify.max_user_watches=524288` resolve).

**Trabalho futuro para garantir o funcionamento em Linux:**

1. validar o watcher em Linux nativo, em container Docker e no WSL2;
2. oferecer um modo de polling (`PollingObserver` do próprio watchdog, por
   exemplo com `docserver watch --polling`) para os ambientes em que o
   `inotify` não recebe eventos;
3. documentar a execução do watcher como serviço (unit do systemd e/ou um
   serviço no `docker-compose.yml`).

Enquanto isso não existir, nesses ambientes rode `docserver ingest`
manualmente depois de mudar os documentos.

## Configuração por projeto (`.docserver.toml`)

Um projeto que usa o docserver leva um `.docserver.toml` na raiz, normalmente
gerado por `docserver init` (ver `docs/AGENTES.md`). Sem o arquivo, nada muda:
valem `docs-fonte/`, `docs-normalizado/` e `data/indice.db` relativos ao
diretório atual, com embeddings ligados e nada extra ignorado.

```toml
[docs]
fonte = "docs"                       # pasta de origem dos documentos
normalizado = ".docserver/normalizado"
indice = ".docserver/indice.db"
embeddings = false                   # false equivale a --sem-embeddings
ignorar = ["_pendentes", "_rejeitados", "_revisoes.jsonl"]   # relativos a `fonte`
```

| Chave | Padrão sem a chave | O que faz |
|---|---|---|
| `docs.fonte` | `docs-fonte` | Pasta de origem dos documentos (equivale a `--docs-fonte`). |
| `docs.normalizado` | `docs-normalizado` | Onde ficam os `.md` normalizados (`--docs-normalizado`). |
| `docs.indice` | `data/indice.db` | Arquivo do índice (`--indice`). |
| `docs.embeddings` | `true` | `false` faz ingestão e watcher serem só léxicos, como `--sem-embeddings`. |
| `docs.ignorar` | `[]` | Padrões que a ingestão e o watcher não leem (ver "Regras de ignorar"). |

A tabela `[revisor]` (comando, modelo, pastas, tentativas) é interpretada pelo
`docserver revisar`; está descrita em `docs/AGENTES.md`.

- **Como é encontrado.** O docserver sobe a partir do diretório atual, pasta por
  pasta até a raiz do disco, e usa o primeiro `.docserver.toml` que achar (como o
  git faz com `.git`). Por isso os comandos funcionam de qualquer subpasta do
  projeto.
- **Caminhos relativos** do arquivo valem a partir da **pasta do
  `.docserver.toml`**, nunca do diretório atual.
- **Precedência:** argumento da linha de comando > arquivo > padrão. Um
  `--docs-fonte` ou `--indice` explícito sempre vence o arquivo (e, sendo
  relativo, vale a partir do diretório atual). Uma exceção de mão única:
  `--sem-embeddings` só liga o modo léxico; com `embeddings = false` no arquivo
  não há flag que o desligue.
- **Chaves desconhecidas** são ignoradas. **Erro de configuração** (TOML
  inválido ou tipo errado, como `embeddings = "nao"`) imprime
  `docserver: configuração inválida: <arquivo>: ...` em stderr e sai com código
  **2**, antes de executar o comando. Só o `docserver init` dispensa o arquivo.
- As pastas `[revisor].pendentes` e `[revisor].rejeitados` e o `[revisor].registro`
  entram em `ignorar` sempre que existe um `.docserver.toml`, mesmo que a lista não
  as cite: a quarentena de `docs/AGENTES.md` não depende de configuração.

### Regras de ignorar

Valem para a ingestão e para o watcher, sempre sobre o caminho **relativo à pasta
de origem**, em formato POSIX. Um arquivo é ignorado se:

- qualquer parte do caminho começa com `.` (pasta ou arquivo oculto, em qualquer
  nível: `.git/`, `.docserver/`, `a/.rascunho/b.md`);
- o nome começa com `~$` (temporário do Office);
- algum padrão de `ignorar` casa (`fnmatch`) com o caminho **ou com qualquer pasta
  ancestral** dele. Assim `"_pendentes"` (ou `"_pendentes/*"`) ignora a pasta
  inteira, e `"*.rascunho.md"` ignora esses arquivos em qualquer lugar.

Ignorado pelas regras não aparece em "Ignorados (formato)" do relatório: é como
se o arquivo não existisse.

### Front matter da origem

Um `.md` de origem que já traz front matter (os documentos escritos por agentes
trazem `titulo`, `tipo`, `gerado_por`...) tem o bloco separado do corpo e
**mesclado** ao do docserver, num bloco só; antes, o original virava texto
indexado. O parser aceita BOM e fins de linha CRLF, e um bloco aberto e nunca
fechado conta como texto comum. Quem vence em caso de conflito:

- `origem`, `extrator` e `ingerido_em` são sempre os calculados pelo docserver
  (um `origem:` copiado de outro lugar estaria errado);
- as demais chaves (`titulo`, `tipo`, `gerado_por`, `commit`, `arquivos`,
  `revisado_por`...) são preservadas como o autor as escreveu.

### `origem` com o nome real da pasta

O `origem:` do normalizado, e portanto o `caminho_origem` que `buscar` mostra e
cita, usa o **nome real da pasta de origem**: com `fonte = "docs"`, um arquivo vira
`docs/conhecimento/x.md`, e não mais o `docs-fonte/` fixo de antes. Com
`--docs-fonte .`, usa o nome da pasta atual. Índices criados antes disso guardam
o prefixo antigo: rode `docserver ingest` uma vez.

### Lock de ingestão

Watcher, `docserver ingest` e `docserver revisar` podem rodar ao mesmo tempo sobre
o mesmo índice, e duas ingestões simultâneas se atropelariam (uma apagaria como
órfão o que a outra acabou de escrever). Cada ingestão segura um lock exclusivo
em `<indice>.ingestao.lock`, ao lado do índice (por exemplo
`.docserver/indice.db.ingestao.lock`):

- se já houver outra em andamento, espera a vez por **até 300 s**. O
  `docserver ingest` avisa `aguardando outra ingestão terminar…` em stderr;
- esgotado o tempo, aborta sem alterar nada (`Ingestão abortada: ...`, código 1;
  no watcher, só registra e segue observando);
- é um **lock do sistema operacional** (`msvcrt.locking` no Windows, `flock` no
  POSIX), e não a existência do arquivo: se o processo morre, o SO solta o lock, e
  um `.lock` largado por uma execução antiga não trava nada. Pode apagá-lo à
  vontade;
- o índice em memória (`:memory:`, usado em testes) não usa lock.

O `docserver revisar` usa um segundo lock, `<indice>.revisao.lock`, para que o
watcher e uma revisão manual não avaliem o mesmo pendente duas vezes.

## Formatos suportados

| Extensão | Estratégia |
|---|---|
| `.md`, `.markdown`, `.txt` | cópia direta |
| `.docx`, `.pptx`, `.xlsx`, `.html` | `markitdown` |
| `.pdf` | `pymupdf4llm` (com limpeza de artefatos de formatação); se sair com menos de ~200 caracteres, cai para `markitdown` |
| `.csv` | vira tabela Markdown |

Qualquer outra extensão é ignorada (aparece em "Ignorados" no relatório, não
derruba a ingestão). Arquivos ocultos (começam com `.`) e temporários do
Office (`~$arquivo.docx`) também são ignorados silenciosamente.

## Lendo o relatório de ingestão

```
Ingestão concluída em 4.2s

  Arquivos processados:   38
  Chunks indexados:      412
  Ignorados (formato):     3
  Falhas de extração:      1
  Suspeitos (texto vazio): 2
  Removidos (órfãos):      1

Falhas:
  ✗ docs-fonte/antigo/manual.doc — formato .doc não suportado (converta para .docx)

Suspeitos (provável PDF escaneado, sem texto extraível):
  ? docs-fonte/legado/fluxo-2019.pdf

Removidos (fonte original não existe mais):
  - docs-normalizado/legado/contrato-antigo.pdf.md
```

- **Ignorados** — extensão sem extrator registrado. Converta o arquivo para
  um formato suportado, ou registre um extrator novo (veja abaixo).
- **Falhas** — o extrator foi chamado mas levantou uma exceção (arquivo
  corrompido, senha protegendo o arquivo, etc.). O restante do lote continua
  normalmente.
- **Suspeitos** — a extração rodou sem erro, mas o resultado ficou vazio ou
  quase vazio. O caso mais comum é PDF escaneado sem OCR (fora de escopo
  desta versão — veja `docs/ARQUITETURA.md`).
- **Removidos** — o `.md` normalizado existia de uma ingestão anterior, mas a
  fonte em `docs-fonte/` não existe mais (foi apagada, renomeada, ou passou a
  falhar na extração). O arquivo é apagado de `docs-normalizado/` e sai do
  índice na mesma ingestão.
- **Preservados** — `.md` em `docs-normalizado/` que não foi gerado pelo
  docserver. Não é indexado nem apagado.
- **Falhas** também inclui colisões: dois arquivos de origem que cairiam no
  mesmo `.md` normalizado (ex.: `Guia.md` e `guia.md` num sistema de arquivos
  que ignora maiúsculas). O segundo não é gravado.

## Quando a extração sai ruim

1. Abra o arquivo correspondente em `docs-normalizado/` e compare com o
   original — o Markdown intermediário existe justamente para essa inspeção.
2. Para PDFs com texto embaralhado ou incompleto, o front matter do arquivo
   normalizado registra qual extrator foi usado (`pymupdf4llm` ou
   `markitdown`); no atual não há como forçar manualmente um extrator por
   arquivo — ajuste `_extrair_pdf` em `src/docserver/extract.py` se um dos
   dois for consistentemente melhor para o seu tipo de PDF. `pymupdf4llm` às
   vezes fragmenta palavras em runs de 1-3 caracteres por variação de fonte
   no PDF original (ex.: PDFs com kerning por caractere) — `_limpar_markdown_pdf`
   tira o negrito/tachado espúrio ao redor dessas runs, mas não reconstrói a
   palavra partida; isso fica visível comparando o `.md` normalizado com o
   PDF original.
3. Para planilhas grandes ou complexas, `markitdown` extrai uma
   representação em texto/tabela — formatação, fórmulas e gráficos não são
   preservados.

## Adicionando um extrator novo

A arquitetura é plugável: um extrator é uma função `Path -> str` registrada
no dicionário `EXTRATORES`, em `src/docserver/extract.py`.

```python
def _extrair_rtf(caminho: Path) -> str:
    # sua lógica de conversão para Markdown aqui
    ...
    return texto_em_markdown

EXTRATORES[".rtf"] = _extrair_rtf
```

Se a extração puder falhar, deixe a exceção propagar normalmente —
`extrair_texto` a envolve em `ErroDeExtracao`, e a ingestão já sabe
registrar isso no relatório sem derrubar o processo.

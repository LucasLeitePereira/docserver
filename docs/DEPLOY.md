# Deploy

## Local

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[embeddings,dev]"
docserver ingest
docserver serve
```

Sem a extra `embeddings` (`pip install -e .`), a busca funciona em modo
léxico puro — útil para desenvolvimento rápido sem baixar `sentence-transformers`/`torch`.

## Docker

```bash
docker compose build
docker compose run --rm docserver docserver ingest
docker compose run --rm docserver docserver search "sua pergunta"
```

O `docker-compose.yml` faz bind mount de `docs-fonte/`, `docs-normalizado/`
e `data/` — edite os arquivos fonte do lado de fora do container
normalmente, e rode `ingest` de novo dentro dele.

O build também baixa o reranker padrão (`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`)
além do `multilingual-e5-small`, porque a imagem roda com `HF_HUB_OFFLINE=1` e sem
ele a busca cairia no fallback sem reranking. A imagem cresce na ordem de algumas
centenas de MB (estimativa, o tamanho não foi medido).

Para uma imagem mais leve, sem a camada vetorial (só BM25):

```bash
docker compose build --build-arg COM_EMBEDDINGS=false
```

### Servidor MCP no container

Há dois modos, e ambos já existem no `docserver serve`:

- **stdio** (serviço `docserver`): o cliente MCP executa
  `docker compose run --rm -T docserver docserver serve` como comando do
  servidor. O compose não usa `tty`: o TTY converte `\n` em `\r\n` e corrompe o
  JSON-RPC. Em `docker run` manual, use `-i` sem `-t`; com `compose run`, use `-T`.
- **HTTP** (serviço `docserver-http`, profile `http`):
  `docker compose --profile http up docserver-http` publica o servidor em
  `http://localhost:8765/mcp`, só no loopback do host. Não há autenticação
  (TASK-010): não publique a porta em outras interfaces.

### Sem chamadas de rede no startup

O `docserver serve` e o `server-mcp` definem, antes de importar o FastMCP e o
`sentence_transformers` (sem sobrescrever o que você já exportou):

| Variável | Padrão no `serve` | Efeito |
|---|---|---|
| `HF_HUB_DISABLE_TELEMETRY` | `1` | desliga a telemetria do Hugging Face |
| `FASTMCP_CHECK_FOR_UPDATES` | `off` | desliga a consulta ao PyPI no banner |
| `HF_HUB_OFFLINE` | `1` | usa só os modelos em cache, sem consultar o Hub |
| `DOCSERVER_PERMITIR_DOWNLOAD` | (não definida) | com `1`, o `serve` não força `HF_HUB_OFFLINE`, para baixar um modelo novo |

O `docker-compose.yml` registra as três primeiras. Para baixar um modelo novo
(por exemplo ao trocar `RERANKER`), suba uma vez com `HF_HUB_OFFLINE=0`
(`docker compose run --rm -e HF_HUB_OFFLINE=0 docserver docserver search "x"`)
ou, fora do Docker, com `DOCSERVER_PERMITIR_DOWNLOAD=1`.

Docker é adequado para ingestão/validação em CI ou numa VM/Codespace
compartilhada; para um cliente MCP local, a instalação direta costuma ser mais
simples.

## Codespaces / VM

Este repositório inclui um `.devcontainer/devcontainer.json` mínimo. Ao abrir
o projeto num GitHub Codespace, o ambiente já sobe com o Dockerfile deste
projeto — rode `docserver ingest` e `docserver serve` normalmente de dentro
do Codespace.

Numa VM comum, os passos são os mesmos da seção "Local" acima — só garanta
Python 3.11+ disponível.

## Roteiro de demonstração

1. `docker compose build` (ou `pip install -e ".[embeddings,dev]"` local).
2. `docserver ingest` — mostre o relatório (contagens, sem falhas).
3. `docserver search "um termo técnico exato"` — mostre que o resultado
   vem com arquivo de origem e seção.
4. `docserver search "a mesma pergunta em linguagem natural"` — mostre que
   a busca híbrida encontra o mesmo documento por um caminho diferente.
5. `docserver avaliar avaliacao/perguntas.yaml` — mostre a tabela
   comparativa léxico / vetorial / híbrido.
6. Conecte um cliente MCP (`docs/AGENTES.md`) e faça a mesma pergunta ao
   agente — mostre que ele cita o arquivo de origem em vez de responder de
   memória.

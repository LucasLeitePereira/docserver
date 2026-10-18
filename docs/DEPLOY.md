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

Para uma imagem mais leve, sem a camada vetorial (só BM25):

```bash
docker compose build --build-arg COM_EMBEDDINGS=false
```

### Servidor MCP no container

O compose tem dois serviços sobre a mesma imagem:

| Serviço | Para quê | Como subir |
|---|---|---|
| `docserver-http` | MCP via HTTP, sempre no ar | `docker compose up -d` |
| `docserver` (profile `cli`) | comandos avulsos e MCP via stdio | `docker compose run --rm -T docserver ...` |

**HTTP (recomendado com Docker).** `docker compose up -d` sobe só o
`docserver-http`, em `http://127.0.0.1:8765/mcp`. O cliente MCP conecta pela
URL, sem precisar saber rodar o container:

```bash
claude mcp add --transport http docserver http://127.0.0.1:8765/mcp
```

Com o `docserver-http` no ar, rode a ingestão **dentro dele**, não num
container novo:

```bash
docker compose exec docserver-http docserver ingest
```

O índice usa o modo WAL do SQLite, cujo arquivo de memória compartilhada
(`indice.db-shm`) não é compartilhado entre containers num bind mount do
Docker Desktop: um `docker compose run` com o servidor HTTP aberto falha com
`unable to open database file`. Pelo mesmo motivo, não abra o mesmo `data/`
ao mesmo tempo pelo host (venv) e por um container. O `docker compose run`
continua valendo quando o `docserver-http` está parado.

A porta é publicada só no loopback do host (`127.0.0.1:8765`), porque o
servidor não tem autenticação. Para expor na rede, troque o mapeamento em
`ports` sabendo que qualquer um na rede passa a ler toda a documentação. Não
use junto com `docserver server-mcp` no host: os dois disputam a porta 8765.
O modelo de embeddings é carregado em segundo plano na subida; as buscas que
chegarem antes disso esperam o carregamento.

**stdio.** O cliente MCP roda o container como se fosse o comando do servidor:

```json
{
  "mcpServers": {
    "docserver": {
      "command": "docker",
      "args": ["compose", "-f", "/caminho/absoluto/docker-compose.yml",
               "run", "--rm", "-T", "docserver", "docserver", "serve"]
    }
  }
}
```

O `-T` e a ausência de `tty` no compose são obrigatórios: um pseudo-TTY
converte `\n` em `\r\n` e corrompe as mensagens JSON-RPC. Cada conexão sobe um
container novo e paga o carregamento do modelo, então o HTTP costuma ser
melhor; o stdio serve para clientes que só aceitam comando.

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

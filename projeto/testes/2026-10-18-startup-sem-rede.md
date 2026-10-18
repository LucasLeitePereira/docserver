# Verificação: startup do servidor sem chamadas de rede

- **Data:** 2026-10-18
- **Tarefas:** TASK-053, TASK-011
- **Máquina:** DESKTOP-AN376AD, Windows 11 Pro 10.0.26300, Python 3.14, CPU
- **Commit:** 48b2adc (branch `fix/compose-e-startup`)
- **Comando:** `python medir.py`, que importa `docserver.embed` e chama
  `embed.embeddar_consulta("aquecimento")` (import de torch + carga do
  `multilingual-e5-small` + um encode), cronometrado com `time.perf_counter()`.
  O comando rodou com `PYTHONPATH=src` e as envs abaixo.

## Resultados brutos

| Ordem | Envs | Aquecimento dos embeddings |
|---|---|---|
| 1 | `HF_HUB_OFFLINE=0` | 161,8 s (cache de disco frio) |
| 2 | `HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1` | 14,9 s |
| 3 | `HF_HUB_OFFLINE=0` | 12,2 s |

## Leitura

Esta medição **não é conclusiva** sobre o ganho de rede. A execução 1 pagou
o cache de disco frio (a máquina estava com o Docker em build), e na
comparação com cache quente a execução com rede (12,2 s) não foi mais lenta
que a offline (14,9 s). Nesta rede, o Hub respondeu rápido; os 50 a 135 s
descritos na TASK-053 vieram de uma máquina com pouca memória livre e rede
lenta. O que as envs garantem é a ausência da dependência de rede, não um
tempo menor em toda máquina. Falta repetir a medição na máquina da
investigação original, ou sem rede, e verificar com um proxy/log que nenhuma
requisição HTTP sai durante o `serve`.

## Docker

- `docker compose build`: a 1ª tentativa falhou na etapa de `apt-get` com
  `failed to receive status: rpc error: code = Unavailable desc = error reading
  from server: EOF` (daemon indisponível, com `No space left on device`
  visto ao gravar o log). A 2ª tentativa ficou mais de 30 min sem concluir e foi
  interrompida. `compose run ingest/search` e o handshake `initialize` pelo
  container **não foram verificados**.

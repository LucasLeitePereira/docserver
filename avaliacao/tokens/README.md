# Medição de tokens: o MCP docserver compensa?

Compara o custo do Claude Code em headless **com** e **sem** o MCP docserver (com conhecimento
revisado), nas mesmas tarefas, partindo sempre do mesmo commit do projeto piloto.

**Aviso de custo:** são `N tarefas x 2 variantes x repetições` execuções reais do Claude (3
repetições por padrão, porque a variância do agente é alta). 5 tarefas x 2 x 3 = 30 execuções
pagas. Comece com 1 tarefa e `--repeticoes 1` para validar o ambiente.

## Como rodar

```
cp avaliacao/tokens/tarefas.example.toml avaliacao/tokens/tarefas.toml   # e edite
python -m avaliacao.tokens.medir medir avaliacao/tokens/tarefas.toml --repeticoes 3
python -m avaliacao.tokens.medir resumir avaliacao/tokens/resultados/<timestamp>.jsonl
```

(`python avaliacao/tokens/medir.py ...` também funciona; só usa a biblioteca padrão.)

Opções do `medir`: `--comando-claude` (padrão `claude`), `--comando-serve` (padrão
`docserver serve`, vira o servidor MCP da variante `com_mcp`), `--comando-ingest` (padrão
`docserver ingest`, rodado na cópia antes da variante `com_mcp`; vazio para pular) e `--saida`.

Cada rodada vira uma linha em `resultados/<timestamp>.jsonl` (gitignored), e o resumo em
Markdown vai para `<timestamp>.md` ao lado. Rodada com erro (JSON inválido, processo com falha,
timeout) é registrada e não derruba a medição: conta como falha na taxa de sucesso e fica fora das
médias de custo.

## Como montar as tarefas

Formato em `tarefas.example.toml`: `repositorio` e `commit` no topo; por tarefa, `id`, `prompt`,
`verificacao` e, opcionalmente, `timeout_s`.

- **Critério de sucesso verificável:** `verificacao` é um comando shell rodado na cópia depois do
  Claude; exit 0 = sucesso. Prefira um teste automatizado que falha antes e passa depois. Nada de
  "parece certo".
- **Tarefas que dependem de conhecimento do projeto**, não só de ler código: uma decisão cuja
  razão não está no código, uma armadilha que custou investigação, uma convenção não óbvia. Se
  o código sozinho basta, a variante `sem_mcp` empata e a medição não ensina nada.
- Tarefas pequenas e independentes, de preferência 5 a 10, para que a média não dependa de uma
  só.
- O projeto piloto precisa ter `.docserver.toml` e o conhecimento em `docs/conhecimento/`
  já commitado no `commit` fixo (ou o índice não terá o que buscar). Confira também que o
  `docserver serve` acha o `.docserver.toml` a partir do diretório da cópia.

## Linha de base e medição posterior

1. **Linha de base:** rode logo que o mecanismo estiver pronto, com pouco conhecimento
   acumulado.
2. **Medição posterior:** semanas depois, com mais conhecimento revisado, rode as **mesmas tarefas**
   (mesmo `commit` de partida; atualize só o conteúdo de `docs/conhecimento/` se for o caso e
   anote isso).
3. Compare os dois `.jsonl` com `resumir`. A variante `sem_mcp` serve de controle: se ela mudar
   muito entre as duas datas, a causa é o modelo ou o ambiente, não o conhecimento.

## Critério de decisão (do plano)

Manter o mecanismo se o **custo médio de `com_mcp` cair** em relação a `sem_mcp` **sem a taxa de
sucesso cair**. Se o custo cair mas o sucesso também, ou se nenhum dos dois mudar, o mecanismo não
se pagou. Com poucas repetições a diferença pode ser ruído: desconfie de variações pequenas.

## Suposições sobre a CLI do Claude (conferir com `claude --help`)

A invocação está centralizada em `montar_comando_claude` (e `configuracao_mcp`) em `medir.py`:

```
<claude> -p <prompt> --output-format json --permission-mode acceptEdits \
         --mcp-config <arquivo> --strict-mcp-config
```

Não foi testada contra o Claude real. A leitura do resultado supõe um objeto JSON com
`total_cost_usd`, `num_turns`, `duration_ms` e `usage` (`input_tokens`, `output_tokens`,
`cache_creation_input_tokens`, `cache_read_input_tokens`); campos ausentes viram `None`. Se algum
nome mudar, ajuste `extrair_metricas`.

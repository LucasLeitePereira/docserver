"""Mede se o MCP docserver reduz o custo em tokens do Claude Code sem derrubar a taxa de sucesso.

Para cada tarefa x variante (com_mcp, sem_mcp) x repetição: cópia limpa do projeto no commit fixo,
Claude em headless, depois a verificação da tarefa. Cada rodada vira uma linha em
resultados/<timestamp>.jsonl; ao fim sai um resumo em Markdown.

Uso:
    python -m avaliacao.tokens.medir medir tarefas.toml --repeticoes 3
    python avaliacao/tokens/medir.py resumir avaliacao/tokens/resultados/<timestamp>.jsonl

Só biblioteca padrão, para rodar como script sem instalar nada.
"""

import argparse
import json
import os
import shlex
import shutil
import statistics
import stat
import subprocess
import sys
import tempfile
import tomllib
from datetime import datetime
from pathlib import Path

VARIANTES = ("com_mcp", "sem_mcp")
TIMEOUT_PADRAO_S = 900
PASTA_RESULTADOS = Path(__file__).resolve().parent / "resultados"
CAMPOS_USO = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


# --- invocação do Claude ------------------------------------------------------------------------


def montar_comando_claude(comando_claude, prompt, arquivo_mcp):
    """Monta a linha de comando do Claude headless.

    SUPOSIÇÃO: estas flags precisam ser conferidas com `claude --help` na versão instalada.
    É o único lugar a ajustar se alguma mudar de nome.
    """
    return [
        *comando_claude,
        "-p",
        prompt,
        "--output-format",
        "json",
        "--permission-mode",
        "acceptEdits",
        "--mcp-config",
        str(arquivo_mcp),
        "--strict-mcp-config",
    ]


def configuracao_mcp(variante, comando_serve):
    """Conteúdo do arquivo de mcp-config. Sem MCP, a lista de servidores fica vazia."""
    if variante == "sem_mcp":
        return {"mcpServers": {}}
    return {
        "mcpServers": {
            "docserver": {"command": comando_serve[0], "args": list(comando_serve[1:])}
        }
    }


def dividir_comando(texto):
    """Divide 'docserver serve' em argumentos, tolerando caminhos do Windows (barras invertidas)."""
    partes = shlex.split(texto, posix=(os.name != "nt"))
    return [p[1:-1] if len(p) > 1 and p[0] == p[-1] and p[0] in "\"'" else p for p in partes]


# --- cópia limpa do projeto ---------------------------------------------------------------------


def _remover_somente_leitura(funcao, caminho, _exc):
    # Objetos do git são somente leitura no Windows e o rmtree falha neles.
    os.chmod(caminho, stat.S_IWRITE)
    funcao(caminho)


def remover_arvore(caminho):
    if sys.version_info >= (3, 12):
        shutil.rmtree(caminho, onexc=_remover_somente_leitura, ignore_errors=False)
    else:
        shutil.rmtree(caminho, onerror=_remover_somente_leitura)


def criar_copia_limpa(repositorio, commit, destino):
    """Clona o projeto em `destino` e posiciona no commit. Levanta CalledProcessError se falhar."""
    subprocess.run(
        ["git", "clone", "--quiet", "--no-checkout", str(repositorio), str(destino)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(destino), "checkout", "--quiet", commit],
        check=True,
        capture_output=True,
        text=True,
    )


# --- extração do resultado ----------------------------------------------------------------------


def extrair_metricas(saida):
    """Lê o JSON do Claude. Devolve (metricas, erro); campos ausentes viram None."""
    vazio = {"total_cost_usd": None, "num_turns": None, "duration_ms": None}
    vazio.update({campo: None for campo in CAMPOS_USO})
    try:
        dados = json.loads(saida)
    except (json.JSONDecodeError, TypeError) as erro:
        return vazio, f"JSON inválido na saída do Claude: {erro}"
    if isinstance(dados, list):  # formato em lista de eventos: vale o último "result"
        resultados = [d for d in dados if isinstance(d, dict) and d.get("type") == "result"]
        dados = resultados[-1] if resultados else None
    if not isinstance(dados, dict):
        return vazio, "saída do Claude não é um objeto JSON"
    uso = dados.get("usage") if isinstance(dados.get("usage"), dict) else {}
    metricas = {
        "total_cost_usd": dados.get("total_cost_usd"),
        "num_turns": dados.get("num_turns"),
        "duration_ms": dados.get("duration_ms"),
    }
    metricas.update({campo: uso.get(campo) for campo in CAMPOS_USO})
    erro = "Claude reportou erro (is_error)" if dados.get("is_error") else None
    return metricas, erro


# --- uma rodada ---------------------------------------------------------------------------------


def _rodar(comando, cwd, timeout, shell=False):
    if not shell:
        # No Windows o CreateProcess não acha shims .cmd (ex.: claude.cmd) sem resolver pelo PATH.
        comando = [shutil.which(comando[0]) or comando[0], *comando[1:]]
    return subprocess.run(
        comando,
        cwd=cwd,
        shell=shell,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def executar_rodada(
    tarefa,
    variante,
    repeticao,
    *,
    repositorio,
    commit,
    comando_claude,
    comando_serve,
    comando_ingest,
    dir_temporario=None,
):
    """Roda uma tarefa numa cópia limpa e devolve o registro (dict). Nunca levanta por falha da rodada."""
    registro = {
        "tarefa": tarefa["id"],
        "variante": variante,
        "repeticao": repeticao,
        "iniciado_em": datetime.now().isoformat(timespec="seconds"),
        "sucesso": False,
        "erro": None,
    }
    base = Path(tempfile.mkdtemp(prefix="medir-", dir=dir_temporario))
    try:
        copia = base / "projeto"
        # O mcp-config fica fora da cópia para não sujar o que a verificação enxerga.
        arquivo_mcp = base / "mcp.json"
        arquivo_mcp.write_text(
            json.dumps(configuracao_mcp(variante, comando_serve)), encoding="utf-8"
        )
        criar_copia_limpa(repositorio, commit, copia)

        if variante == "com_mcp" and comando_ingest:
            ingest = _rodar(comando_ingest, copia, TIMEOUT_PADRAO_S)
            if ingest.returncode != 0:
                raise RuntimeError(f"ingestão falhou (exit {ingest.returncode}): {ingest.stderr[-300:]}")

        timeout = tarefa.get("timeout_s", TIMEOUT_PADRAO_S)
        comando = montar_comando_claude(comando_claude, tarefa["prompt"], arquivo_mcp)
        processo = _rodar(comando, copia, timeout)
        metricas, erro = extrair_metricas(processo.stdout)
        registro.update(metricas)
        if processo.returncode != 0:
            erro = f"Claude saiu com exit {processo.returncode}: {processo.stderr[-300:]}"
        if erro:
            registro["erro"] = erro
        else:
            verificacao = _rodar(tarefa["verificacao"], copia, timeout, shell=True)
            registro["sucesso"] = verificacao.returncode == 0
            if not registro["sucesso"]:
                registro["detalhe_verificacao"] = (verificacao.stdout + verificacao.stderr)[-300:]
    except subprocess.TimeoutExpired as erro:
        registro["erro"] = f"timeout após {erro.timeout}s"
    except Exception as erro:  # a medição segue mesmo que uma rodada quebre
        registro["erro"] = f"{type(erro).__name__}: {erro}"
    finally:
        remover_arvore(base)
    return registro


# --- resumo -------------------------------------------------------------------------------------


def _media(valores):
    valores = [v for v in valores if v is not None]
    return statistics.fmean(valores) if valores else None


def _mediana(valores):
    valores = [v for v in valores if v is not None]
    return statistics.median(valores) if valores else None


def _fmt(valor, casas=2, prefixo=""):
    return "-" if valor is None else f"{prefixo}{valor:.{casas}f}"


def _estatisticas(registros):
    custos = [r.get("total_cost_usd") for r in registros]
    return {
        "n": len(registros),
        "erros": sum(1 for r in registros if r.get("erro")),
        "taxa": sum(1 for r in registros if r.get("sucesso")) / len(registros) if registros else None,
        "custo_medio": _media(custos),
        "custo_mediano": _mediana(custos),
        "entrada": _media([r.get("input_tokens") for r in registros]),
        "saida": _media([r.get("output_tokens") for r in registros]),
        "cache_criacao": _media([r.get("cache_creation_input_tokens") for r in registros]),
        "cache_leitura": _media([r.get("cache_read_input_tokens") for r in registros]),
        "turnos": _media([r.get("num_turns") for r in registros]),
    }


def _diferenca_pct(com, sem):
    if com is None or not sem:
        return None
    return (com - sem) / sem * 100


def gerar_resumo(registros):
    """Resumo em Markdown. Rodadas com erro contam como falha na taxa e ficam fora das médias de custo."""
    por_variante = {v: [r for r in registros if r["variante"] == v] for v in VARIANTES}
    linhas = ["# Medição de tokens", "", f"Rodadas: {len(registros)}", ""]

    linhas += [
        "## Por variante",
        "",
        "| variante | rodadas | erros | sucesso | custo médio (US$) | custo mediano (US$) "
        "| entrada | saída | cache criação | cache leitura | turnos |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    estat = {}
    for variante in VARIANTES:
        e = estat[variante] = _estatisticas(por_variante[variante])
        taxa = "-" if e["taxa"] is None else f"{e['taxa'] * 100:.0f}%"
        linhas.append(
            f"| {variante} | {e['n']} | {e['erros']} | {taxa} | {_fmt(e['custo_medio'], 4)} "
            f"| {_fmt(e['custo_mediano'], 4)} | {_fmt(e['entrada'], 0)} | {_fmt(e['saida'], 0)} "
            f"| {_fmt(e['cache_criacao'], 0)} | {_fmt(e['cache_leitura'], 0)} | {_fmt(e['turnos'], 1)} |"
        )

    linhas += [
        "",
        "## Diferença com_mcp vs sem_mcp",
        "",
        "Custo em % (negativo = o MCP economizou). Sucesso em pontos percentuais.",
        "",
        "| tarefa | custo sem_mcp | custo com_mcp | diferença de custo | sucesso sem_mcp | sucesso com_mcp |",
        "|---|---|---|---|---|---|",
    ]
    tarefas = sorted({r["tarefa"] for r in registros})
    for tarefa in [*tarefas, None]:
        grupo = {
            v: [r for r in por_variante[v] if tarefa is None or r["tarefa"] == tarefa]
            for v in VARIANTES
        }
        e = {v: _estatisticas(grupo[v]) for v in VARIANTES}
        dif = _diferenca_pct(e["com_mcp"]["custo_medio"], e["sem_mcp"]["custo_medio"])
        taxas = [
            "-" if e[v]["taxa"] is None else f"{e[v]['taxa'] * 100:.0f}%"
            for v in ("sem_mcp", "com_mcp")
        ]
        nome = "**TOTAL**" if tarefa is None else tarefa
        linhas.append(
            f"| {nome} | {_fmt(e['sem_mcp']['custo_medio'], 4)} | {_fmt(e['com_mcp']['custo_medio'], 4)} "
            f"| {'-' if dif is None else f'{dif:+.1f}%'} | {taxas[0]} | {taxas[1]} |"
        )
    return "\n".join(linhas) + "\n"


def ler_registros(arquivo):
    registros = []
    for linha in Path(arquivo).read_text(encoding="utf-8").splitlines():
        if linha.strip():
            registros.append(json.loads(linha))
    return registros


# --- medição completa ---------------------------------------------------------------------------


def carregar_tarefas(caminho):
    with open(caminho, "rb") as f:
        dados = tomllib.load(f)
    for campo in ("repositorio", "commit"):
        if campo not in dados:
            raise ValueError(f"'{campo}' ausente em {caminho}")
    tarefas = dados.get("tarefa", [])
    for tarefa in tarefas:
        for campo in ("id", "prompt", "verificacao"):
            if campo not in tarefa:
                raise ValueError(f"tarefa sem '{campo}': {tarefa}")
    return dados["repositorio"], dados["commit"], tarefas


def medir(
    repositorio,
    commit,
    tarefas,
    *,
    repeticoes=3,
    comando_claude=("claude",),
    comando_serve=("docserver", "serve"),
    comando_ingest=("docserver", "ingest"),
    pasta_resultados=PASTA_RESULTADOS,
    dir_temporario=None,
    log=print,
):
    """Roda todas as rodadas, grava o jsonl e o resumo. Devolve (caminho_jsonl, caminho_resumo)."""
    pasta = Path(pasta_resultados)
    pasta.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
    arquivo = pasta / f"{carimbo}.jsonl"
    registros = []
    for tarefa in tarefas:
        for variante in VARIANTES:
            for repeticao in range(1, repeticoes + 1):
                registro = executar_rodada(
                    tarefa,
                    variante,
                    repeticao,
                    repositorio=repositorio,
                    commit=commit,
                    comando_claude=list(comando_claude),
                    comando_serve=list(comando_serve),
                    comando_ingest=list(comando_ingest) if comando_ingest else None,
                    dir_temporario=dir_temporario,
                )
                registros.append(registro)
                with open(arquivo, "a", encoding="utf-8") as f:  # grava já, para não perder em caso de queda
                    f.write(json.dumps(registro, ensure_ascii=False) + "\n")
                situacao = "ok" if registro["sucesso"] else f"falha ({registro['erro'] or 'verificação'})"
                log(f"[{tarefa['id']} | {variante} | {repeticao}/{repeticoes}] {situacao}")
    resumo = gerar_resumo(registros)
    arquivo_resumo = arquivo.with_suffix(".md")
    arquivo_resumo.write_text(resumo, encoding="utf-8")
    log("\n" + resumo)
    return arquivo, arquivo_resumo


def principal(argv=None):
    parser = argparse.ArgumentParser(description="Mede o custo em tokens com e sem o MCP docserver.")
    sub = parser.add_subparsers(dest="comando", required=True)

    p_medir = sub.add_parser("medir", help="roda a medição completa")
    p_medir.add_argument("tarefas", help="arquivo TOML de tarefas (ver tarefas.example.toml)")
    p_medir.add_argument("--repeticoes", type=int, default=3)
    p_medir.add_argument("--comando-claude", default="claude")
    p_medir.add_argument("--comando-serve", default="docserver serve")
    p_medir.add_argument(
        "--comando-ingest", default="docserver ingest", help="vazio para não ingerir antes (com_mcp)"
    )
    p_medir.add_argument("--saida", default=str(PASTA_RESULTADOS))

    p_resumir = sub.add_parser("resumir", help="regera o resumo de um .jsonl antigo")
    p_resumir.add_argument("arquivo")

    args = parser.parse_args(argv)
    if args.comando == "resumir":
        print(gerar_resumo(ler_registros(args.arquivo)))
        return 0

    repositorio, commit, tarefas = carregar_tarefas(args.tarefas)
    medir(
        repositorio,
        commit,
        tarefas,
        repeticoes=args.repeticoes,
        comando_claude=dividir_comando(args.comando_claude),
        comando_serve=dividir_comando(args.comando_serve),
        comando_ingest=dividir_comando(args.comando_ingest) if args.comando_ingest else None,
        pasta_resultados=args.saida,
    )
    return 0


if __name__ == "__main__":
    sys.exit(principal())

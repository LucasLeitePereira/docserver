"""Testes do harness avaliacao/tokens/medir.py, com um "Claude falso" (sem rede, sem custo)."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from avaliacao.tokens import medir  # noqa: E402

CLAUDE_FALSO = textwrap.dedent(
    """
    import json, sys
    from pathlib import Path

    args = sys.argv[1:]
    prompt = args[args.index("-p") + 1]
    config = json.loads(Path(args[args.index("--mcp-config") + 1]).read_text())
    if Path("marcador.txt").exists():  # cópia suja: sobrou rastro de outra rodada
        print("copia suja", file=sys.stderr)
        sys.exit(3)
    Path("marcador.txt").write_text("x")
    if prompt == "json_invalido":
        print("isto nao e json")
        sys.exit(0)
    if prompt != "nao_resolver":
        Path("feito.txt").write_text("ok")
    com_mcp = bool(config["mcpServers"])
    print(json.dumps({
        "type": "result",
        "total_cost_usd": 0.5 if com_mcp else 1.0,
        "num_turns": 4 if com_mcp else 8,
        "duration_ms": 1000,
        "usage": {"input_tokens": 10, "output_tokens": 20,
                  "cache_creation_input_tokens": 100, "cache_read_input_tokens": 1000},
    }))
    """
)

VERIFICACAO = f'"{sys.executable}" -c "import pathlib,sys; sys.exit(0 if pathlib.Path(\'feito.txt\').exists() else 1)"'


@pytest.fixture
def repo(tmp_path):
    caminho = tmp_path / "piloto"
    caminho.mkdir()
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(caminho)]
    subprocess.run([*git, "init", "-q"], check=True)
    (caminho / "README.md").write_text("projeto piloto")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "inicial"], check=True)
    commit = subprocess.run(
        [*git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    # Um commit posterior que não deve aparecer nas cópias: o ponto de partida é fixo.
    (caminho / "depois.txt").write_text("posterior")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "depois"], check=True)
    return caminho, commit


@pytest.fixture
def claude_falso(tmp_path):
    script = tmp_path / "claude_falso.py"
    script.write_text(CLAUDE_FALSO, encoding="utf-8")
    return [sys.executable, str(script)]


def _medir(repo, claude_falso, tmp_path, tarefas, repeticoes=2):
    caminho, commit = repo
    trabalho = tmp_path / "trabalho"
    trabalho.mkdir(exist_ok=True)
    arquivo, resumo = medir.medir(
        str(caminho),
        commit,
        tarefas,
        repeticoes=repeticoes,
        comando_claude=claude_falso,
        comando_ingest=None,
        pasta_resultados=tmp_path / "resultados",
        dir_temporario=trabalho,
        log=lambda *_: None,
    )
    return medir.ler_registros(arquivo), arquivo, resumo, trabalho


def test_rodadas_isoladas_e_verificacao_decide_sucesso(repo, claude_falso, tmp_path):
    tarefas = [
        {"id": "resolve", "prompt": "resolver", "verificacao": VERIFICACAO},
        {"id": "falha", "prompt": "nao_resolver", "verificacao": VERIFICACAO},
    ]
    registros, _, _, trabalho = _medir(repo, claude_falso, tmp_path, tarefas, repeticoes=2)

    assert len(registros) == 2 * 2 * 2  # tarefas x variantes x repetições
    # O falso sai com erro se achar marcador.txt: nenhuma rodada pode ter visto rastro de outra.
    assert all(r["erro"] is None for r in registros)
    assert all(r["sucesso"] for r in registros if r["tarefa"] == "resolve")
    assert not any(r["sucesso"] for r in registros if r["tarefa"] == "falha")
    # O custo mudou conforme o mcp-config tinha servidores ou não.
    custos = {r["variante"]: r["total_cost_usd"] for r in registros}
    assert custos == {"com_mcp": 0.5, "sem_mcp": 1.0}
    assert list(trabalho.iterdir()) == []  # diretórios temporários removidos


def test_commit_fixo_nao_traz_commits_posteriores(repo, tmp_path):
    caminho, commit = repo
    copia = tmp_path / "copia"
    medir.criar_copia_limpa(str(caminho), commit, copia)
    assert (copia / "README.md").exists()
    assert not (copia / "depois.txt").exists()
    medir.remover_arvore(copia)
    assert not copia.exists()


def test_json_invalido_vira_erro_sem_derrubar(repo, claude_falso, tmp_path):
    tarefas = [
        {"id": "ruim", "prompt": "json_invalido", "verificacao": VERIFICACAO},
        {"id": "boa", "prompt": "resolver", "verificacao": VERIFICACAO},
    ]
    registros, _, _, trabalho = _medir(repo, claude_falso, tmp_path, tarefas, repeticoes=1)

    ruins = [r for r in registros if r["tarefa"] == "ruim"]
    assert len(ruins) == 2
    assert all("JSON inválido" in r["erro"] and not r["sucesso"] for r in ruins)
    assert all(r["total_cost_usd"] is None for r in ruins)
    assert all(r["sucesso"] for r in registros if r["tarefa"] == "boa")  # seguiu a medição
    assert list(trabalho.iterdir()) == []


def test_comando_inexistente_registra_erro_e_limpa(repo, tmp_path):
    registros, _, _, trabalho = _medir(
        repo,
        ["comando-que-nao-existe-xyz"],
        tmp_path,
        [{"id": "t", "prompt": "p", "verificacao": VERIFICACAO}],
        repeticoes=1,
    )
    assert all(r["erro"] and not r["sucesso"] for r in registros)
    assert list(trabalho.iterdir()) == []


def test_extrair_metricas_tolera_campos_ausentes():
    metricas, erro = medir.extrair_metricas(json.dumps({"total_cost_usd": 0.1, "usage": {"input_tokens": 5}}))
    assert erro is None
    assert metricas["total_cost_usd"] == 0.1
    assert metricas["input_tokens"] == 5
    assert metricas["num_turns"] is None
    assert metricas["cache_read_input_tokens"] is None


def _registro(tarefa, variante, custo, sucesso=True, turnos=2, erro=None):
    return {
        "tarefa": tarefa,
        "variante": variante,
        "sucesso": sucesso,
        "erro": erro,
        "total_cost_usd": custo,
        "num_turns": turnos,
        "input_tokens": 100,
        "output_tokens": 10,
        "cache_creation_input_tokens": None,
        "cache_read_input_tokens": None,
    }


def test_resumo_calcula_medias_e_diferenca_percentual():
    registros = [
        _registro("a", "sem_mcp", 1.0),
        _registro("a", "sem_mcp", 3.0, sucesso=False),
        _registro("a", "com_mcp", 1.0),
        _registro("a", "com_mcp", 1.0),
        _registro("b", "sem_mcp", 4.0),
        _registro("b", "com_mcp", 2.0),
    ]
    resumo = medir.gerar_resumo(registros)

    # sem_mcp: custo médio (1+3+4)/3 = 2,6667; com_mcp: (1+1+2)/3 = 1,3333; mediana sem = 3
    assert "| sem_mcp | 3 | 0 | 67% | 2.6667 | 3.0000 |" in resumo
    assert "| com_mcp | 3 | 0 | 100% | 1.3333 | 1.0000 |" in resumo
    assert "| a | 2.0000 | 1.0000 | -50.0% | 50% | 100% |" in resumo
    assert "| b | 4.0000 | 2.0000 | -50.0% | 100% | 100% |" in resumo
    assert "| **TOTAL** | 2.6667 | 1.3333 | -50.0% | 67% | 100% |" in resumo


def test_resumo_com_variante_vazia_nao_quebra():
    resumo = medir.gerar_resumo([_registro("a", "sem_mcp", 1.0)])
    assert "| com_mcp | 0 | 0 | - |" in resumo


def test_resumir_reproduz_o_resumo_do_jsonl(repo, claude_falso, tmp_path, capsys):
    tarefas = [{"id": "resolve", "prompt": "resolver", "verificacao": VERIFICACAO}]
    _, arquivo, resumo, _ = _medir(repo, claude_falso, tmp_path, tarefas, repeticoes=2)

    assert medir.principal(["resumir", str(arquivo)]) == 0
    saida = capsys.readouterr().out
    assert saida.strip() == resumo.read_text(encoding="utf-8").strip()
    assert "-50.0%" in saida


def test_carregar_tarefas_e_exemplo_valido(tmp_path):
    repositorio, commit, tarefas = medir.carregar_tarefas(
        RAIZ / "avaliacao" / "tokens" / "tarefas.example.toml"
    )
    assert repositorio and commit
    assert tarefas and all({"id", "prompt", "verificacao"} <= set(t) for t in tarefas)

    ruim = tmp_path / "ruim.toml"
    ruim.write_text('repositorio = "x"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        medir.carregar_tarefas(ruim)


def test_montar_comando_claude_tem_as_flags_esperadas():
    comando = medir.montar_comando_claude(["claude"], "faça x", Path("mcp.json"))
    assert comando[:3] == ["claude", "-p", "faça x"]
    for flag in ("--output-format", "--permission-mode", "--mcp-config", "--strict-mcp-config"):
        assert flag in comando
    assert medir.configuracao_mcp("sem_mcp", ["docserver", "serve"]) == {"mcpServers": {}}
    assert medir.configuracao_mcp("com_mcp", ["docserver", "serve"])["mcpServers"]["docserver"] == {
        "command": "docserver",
        "args": ["serve"],
    }

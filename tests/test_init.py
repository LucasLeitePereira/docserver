"""Testes do `docserver init` (src/docserver/init.py)."""

import json
import tomllib

from docserver.init import inicializar


def _estado(raiz):
    return {
        str(p.relative_to(raiz)): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in sorted(raiz.rglob("*")) if p.is_file()
    }


def test_projeto_vazio_gera_tudo(tmp_path):
    inicializar(tmp_path)
    assert (tmp_path / ".docserver.toml").is_file()
    for sub in ("conhecimento", "_pendentes", "_rejeitados"):
        assert (tmp_path / "docs" / sub / ".gitkeep").is_file()
    mcp = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp == {"mcpServers": {"docserver": {"command": "docserver", "args": ["serve"]}}}
    claude = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "<!-- docserver:inicio -->" in claude and "<!-- docserver:fim -->" in claude
    assert "`docs/_pendentes/`" in claude
    assert (tmp_path / ".claude/skills/documentar/SKILL.md").is_file()
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == ".docserver/\n"


def test_segunda_execucao_nao_altera_nada(tmp_path):
    inicializar(tmp_path)
    antes = _estado(tmp_path)
    linhas = inicializar(tmp_path)
    assert _estado(tmp_path) == antes
    assert all("já existia" in linha for linha in linhas)


def test_claude_md_preexistente_recebe_bloco_no_fim(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# Meu projeto\nregra minha", encoding="utf-8")
    inicializar(tmp_path)
    texto = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert texto.startswith("# Meu projeto\nregra minha\n")
    assert texto.rstrip().endswith("<!-- docserver:fim -->")
    assert texto.count("<!-- docserver:inicio -->") == 1


def test_mcp_json_preexistente_e_mesclado(tmp_path):
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"outro": {"command": "x"}}}), encoding="utf-8")
    inicializar(tmp_path)
    servidores = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert servidores["outro"] == {"command": "x"}
    assert servidores["docserver"]["args"] == ["serve"]


def test_entrada_docserver_existente_nao_e_alterada(tmp_path):
    original = json.dumps({"mcpServers": {"docserver": {"command": "meu"}}})
    (tmp_path / ".mcp.json").write_text(original, encoding="utf-8")
    linhas = inicializar(tmp_path)
    assert (tmp_path / ".mcp.json").read_text(encoding="utf-8") == original
    assert any("já existia" in linha and ".mcp.json" in linha for linha in linhas)


def test_gitignore_sem_quebra_final(tmp_path):
    (tmp_path / ".gitignore").write_text("venv/", encoding="utf-8")
    inicializar(tmp_path)
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == "venv/\n.docserver/\n"


def test_fonte_do_toml_existente_e_respeitada(tmp_path):
    (tmp_path / ".docserver.toml").write_text('[docs]\nfonte = "documentacao"\n', encoding="utf-8")
    inicializar(tmp_path)
    assert (tmp_path / "documentacao/_pendentes/.gitkeep").is_file()
    assert not (tmp_path / "docs").exists()
    assert "`documentacao/_pendentes/`" in (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    skill = (tmp_path / ".claude/skills/documentar/SKILL.md").read_text(encoding="utf-8")
    assert "documentacao/_pendentes/" in skill and "@@" not in skill


def test_toml_gerado_e_valido_e_tem_o_modelo(tmp_path):
    inicializar(tmp_path, modelo_revisor="modelo-x")
    dados = tomllib.loads((tmp_path / ".docserver.toml").read_text(encoding="utf-8"))
    assert dados["revisor"]["modelo"] == "modelo-x"
    assert dados["docs"]["fonte"] == "docs"
    assert "{modelo}" in dados["revisor"]["comando"]  # placeholder do comando é preservado
    assert dados["docs"]["embeddings"] is False


def test_skill_tem_front_matter(tmp_path):
    inicializar(tmp_path)
    skill = (tmp_path / ".claude/skills/documentar/SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\n")
    cabecalho = skill.split("---")[1]
    assert "name: documentar" in cabecalho and "description:" in cabecalho
    assert len(skill.splitlines()) <= 75

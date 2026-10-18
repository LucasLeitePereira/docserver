"""`docserver init`: prepara um projeto para usar o docserver.

Tudo é idempotente e nunca sobrescreve conteúdo da pessoa: arquivos que já existem são
mantidos (CLAUDE.md, .mcp.json e .gitignore só recebem o que falta). A função é pura em
relação à CLI: devolve linhas legíveis, quem imprime é o cli.py.
"""

from __future__ import annotations

import json
import tomllib
from importlib.resources import files
from pathlib import Path

NOME_TOML = ".docserver.toml"
MARCA_INICIO = "<!-- docserver:inicio -->"
MARCA_FIM = "<!-- docserver:fim -->"
FONTE_PADRAO = "docs"
SUBPASTAS = ("conhecimento", "_pendentes", "_rejeitados")


def _modelo(nome: str) -> str:
    return (files("docserver") / "modelos" / nome).read_text(encoding="utf-8")


def _ler(caminho: Path) -> str:
    return caminho.read_text(encoding="utf-8")


def _escrever(caminho: Path, texto: str) -> None:
    # newline="" evita que o Windows converta \n em \r\n e bagunce arquivos versionados.
    with open(caminho, "w", encoding="utf-8", newline="") as f:
        f.write(texto)


def _descobrir_fonte(raiz: Path) -> str:
    """Lê `[docs].fonte` de um .docserver.toml já existente; senão, o padrão."""
    arquivo = raiz / NOME_TOML
    if arquivo.is_file():
        try:
            dados = tomllib.loads(_ler(arquivo))
            fonte = dados.get("docs", {}).get("fonte")
            if isinstance(fonte, str) and fonte.strip():
                return fonte.strip().strip("/\\")
        except (tomllib.TOMLDecodeError, OSError):
            pass
    return FONTE_PADRAO


def _toml(raiz: Path, modelo_revisor: str) -> str:
    arquivo = raiz / NOME_TOML
    if arquivo.exists():
        return f"já existia: {NOME_TOML}"
    _escrever(arquivo, _modelo("docserver.toml").replace("@@MODELO@@", modelo_revisor))
    return f"criado {NOME_TOML}"


def _pastas(raiz: Path, fonte: str) -> list[str]:
    saida = []
    for sub in SUBPASTAS:
        pasta = raiz / fonte / sub
        marca = pasta / ".gitkeep"
        rel = f"{fonte}/{sub}"
        if marca.exists():
            saida.append(f"já existia: {rel}/.gitkeep")
            continue
        existia = pasta.is_dir()
        pasta.mkdir(parents=True, exist_ok=True)
        marca.touch()
        saida.append(f"{'adicionado .gitkeep em' if existia else 'criada pasta'} {rel}/")
    return saida


def _mcp(raiz: Path) -> str:
    arquivo = raiz / ".mcp.json"
    entrada = {"command": "docserver", "args": ["serve"]}
    if not arquivo.exists():
        _escrever(arquivo, json.dumps({"mcpServers": {"docserver": entrada}}, indent=2) + "\n")
        return "criado .mcp.json"
    try:
        dados = json.loads(_ler(arquivo))
    except json.JSONDecodeError:
        return "AVISO: .mcp.json não é JSON válido; não alterado (adicione a entrada docserver à mão)"
    if not isinstance(dados, dict) or not isinstance(dados.get("mcpServers", {}), dict):
        return "AVISO: .mcp.json com formato inesperado; não alterado"
    servidores = dados.setdefault("mcpServers", {})
    if "docserver" in servidores:
        return "já existia: entrada docserver em .mcp.json"
    servidores["docserver"] = entrada
    _escrever(arquivo, json.dumps(dados, indent=2, ensure_ascii=False) + "\n")
    return "anexada entrada docserver ao .mcp.json"


def _claude_md(raiz: Path, fonte: str) -> str:
    arquivo = raiz / "CLAUDE.md"
    bloco = _modelo("claude-md.md").replace("@@FONTE@@", fonte).rstrip("\n") + "\n"
    if not arquivo.exists():
        _escrever(arquivo, bloco)
        return "criado CLAUDE.md com o bloco do docserver"
    atual = _ler(arquivo)
    if MARCA_INICIO in atual:
        return "já existia: bloco do docserver no CLAUDE.md"
    if atual and not atual.endswith("\n"):
        atual += "\n"
    separador = "\n" if atual.strip() else ""
    _escrever(arquivo, atual + separador + bloco)
    return "anexado bloco ao CLAUDE.md"


def _skill(raiz: Path, fonte: str) -> str:
    arquivo = raiz / ".claude" / "skills" / "documentar" / "SKILL.md"
    if arquivo.exists():
        return "já existia: .claude/skills/documentar/SKILL.md"
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    _escrever(arquivo, _modelo("skill-documentar.md").replace("@@FONTE@@", fonte))
    return "criada skill .claude/skills/documentar/SKILL.md"


def _gitignore(raiz: Path) -> str:
    arquivo = raiz / ".gitignore"
    if not arquivo.exists():
        _escrever(arquivo, ".docserver/\n")
        return "criado .gitignore com .docserver/"
    atual = _ler(arquivo)
    if ".docserver/" in (linha.strip() for linha in atual.splitlines()):
        return "já existia: .docserver/ no .gitignore"
    if atual and not atual.endswith("\n"):
        atual += "\n"
    _escrever(arquivo, atual + ".docserver/\n")
    return "anexado .docserver/ ao .gitignore"


def inicializar(raiz: Path, *, modelo_revisor: str = "claude-sonnet-5-5") -> list[str]:
    """Prepara `raiz` para o docserver e devolve o relato do que foi feito."""
    raiz = Path(raiz)
    raiz.mkdir(parents=True, exist_ok=True)
    linhas = [_toml(raiz, modelo_revisor)]
    # A fonte vem do toml (recém-criado ou já existente) para pastas e textos concordarem.
    fonte = _descobrir_fonte(raiz)
    linhas += _pastas(raiz, fonte)
    linhas.append(_mcp(raiz))
    linhas.append(_claude_md(raiz, fonte))
    linhas.append(_skill(raiz, fonte))
    linhas.append(_gitignore(raiz))
    return linhas

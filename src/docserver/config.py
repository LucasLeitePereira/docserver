"""Configuração por projeto: o `.docserver.toml` na raiz de quem usa o docserver.

Sem o arquivo, valem os caminhos de sempre (relativos ao cwd). Com ele, os caminhos
relativos são resolvidos a partir da pasta do arquivo — não do cwd —, para que o
comando funcione igual de qualquer subpasta do projeto (como o git faz com `.git`).
"""

from __future__ import annotations

import copy
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

NOME_ARQUIVO = ".docserver.toml"

DOCS_FONTE_PADRAO = Path("docs-fonte")
DOCS_NORMALIZADO_PADRAO = Path("docs-normalizado")
INDICE_PADRAO = "data/indice.db"

REVISOR_PADRAO: dict = {
    "comando": [
        "claude",
        "-p",
        "--model",
        "{modelo}",
        "--output-format",
        "json",
        "--allowedTools",
        "Read,Grep,Glob",
        # sem os MCP do projeto: o revisor não precisa do próprio docserver (os parecidos
        # já vão no prompt) e subir o servidor a cada revisão só atrasa
        "--strict-mcp-config",
    ],
    "modelo": "claude-sonnet-5-5",
    "pendentes": "_pendentes",
    "aprovados": "conhecimento",
    "rejeitados": "_rejeitados",
    "registro": "_revisoes.jsonl",
    "max_tentativas": 3,
}


@dataclass(frozen=True)
class Config:
    raiz: Path | None
    docs_fonte: Path = DOCS_FONTE_PADRAO
    docs_normalizado: Path = DOCS_NORMALIZADO_PADRAO
    indice: Path = Path(INDICE_PADRAO)
    embeddings: bool = True
    ignorar: tuple[str, ...] = ()
    revisor: dict = field(default_factory=lambda: copy.deepcopy(REVISOR_PADRAO))


def encontrar(inicio: Path | None = None) -> Path | None:
    """Sobe de `inicio` (padrão: cwd) até a raiz do disco procurando o arquivo."""
    pasta = Path(inicio if inicio is not None else Path.cwd()).resolve()
    for candidata in (pasta, *pasta.parents):
        arquivo = candidata / NOME_ARQUIVO
        if arquivo.is_file():
            return arquivo
    return None


def _erro(arquivo: Path, chave: str, esperado: str) -> ValueError:
    return ValueError(f"{arquivo}: a chave '{chave}' deve ser {esperado}")


def _texto(tabela: dict, chave: str, arquivo: Path, rotulo: str) -> str | None:
    if chave not in tabela:
        return None
    valor = tabela[chave]
    if not isinstance(valor, str):
        raise _erro(arquivo, rotulo, "um texto")
    return valor


def _lista_de_textos(valor, arquivo: Path, rotulo: str) -> list[str]:
    if not isinstance(valor, list) or not all(isinstance(item, str) for item in valor):
        raise _erro(arquivo, rotulo, "uma lista de textos")
    return list(valor)


def carregar(inicio: Path | None = None) -> Config:
    """Lê o `.docserver.toml` encontrado a partir de `inicio`. Sem arquivo, devolve os
    padrões com `raiz=None`. Chaves desconhecidas são ignoradas; tipo errado ou TOML
    inválido levantam `ValueError` citando o arquivo (e a chave)."""
    arquivo = encontrar(inicio)
    if arquivo is None:
        return Config(raiz=None)

    try:
        with arquivo.open("rb") as f:
            dados = tomllib.load(f)
    except tomllib.TOMLDecodeError as erro:
        raise ValueError(f"{arquivo}: TOML inválido ({erro})") from erro

    raiz = arquivo.parent

    docs = dados.get("docs", {})
    if not isinstance(docs, dict):
        raise _erro(arquivo, "docs", "uma tabela")

    def caminho(chave: str, padrao: Path) -> Path:
        valor = _texto(docs, chave, arquivo, f"docs.{chave}")
        return raiz / (valor if valor is not None else padrao)

    embeddings = docs.get("embeddings", True)
    if not isinstance(embeddings, bool):
        raise _erro(arquivo, "docs.embeddings", "verdadeiro ou falso (true/false)")
    ignorar = _lista_de_textos(docs.get("ignorar", []), arquivo, "docs.ignorar")

    revisor_arquivo = dados.get("revisor", {})
    if not isinstance(revisor_arquivo, dict):
        raise _erro(arquivo, "revisor", "uma tabela")
    revisor = {**copy.deepcopy(REVISOR_PADRAO), **revisor_arquivo}
    revisor["comando"] = _lista_de_textos(revisor["comando"], arquivo, "revisor.comando")
    for chave in ("modelo", "pendentes", "aprovados", "rejeitados", "registro"):
        if not isinstance(revisor[chave], str):
            raise _erro(arquivo, f"revisor.{chave}", "um texto")
    tentativas = revisor["max_tentativas"]
    if isinstance(tentativas, bool) or not isinstance(tentativas, int):
        raise _erro(arquivo, "revisor.max_tentativas", "um número inteiro")

    # A quarentena não depende de a pessoa lembrar do `ignorar`: o que não passou pelo
    # revisor (pendentes, rejeitados) e o registro de auditoria nunca entram no índice.
    for chave in ("pendentes", "rejeitados", "registro"):
        padrao = revisor[chave].strip("/\\").replace("\\", "/")
        if padrao and padrao not in ignorar:
            ignorar.append(padrao)

    return Config(
        raiz=raiz,
        docs_fonte=caminho("fonte", DOCS_FONTE_PADRAO),
        docs_normalizado=caminho("normalizado", DOCS_NORMALIZADO_PADRAO),
        indice=caminho("indice", Path(INDICE_PADRAO)),
        embeddings=embeddings,
        ignorar=tuple(ignorar),
        revisor=revisor,
    )

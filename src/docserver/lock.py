"""Lock exclusivo entre processos para serializar ingestões (e, depois, revisões).

Watcher, `docserver ingest` e o revisor podem rodar ao mesmo tempo sobre o mesmo índice e
o mesmo docs-normalizado; duas ingestões simultâneas se atropelam (uma apaga como órfão o
que a outra acabou de escrever). O lock é do sistema operacional (`msvcrt.locking` no
Windows, `fcntl.flock` no POSIX), nunca a existência do arquivo: se o processo morre, o SO
solta o lock, e um arquivo largado por uma execução antiga não trava nada.

Não é reentrante: aninhar `travar` sobre o mesmo caminho, no mesmo processo ou em outro,
espera o próprio lock e termina em `LockOcupado`.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


class LockOcupado(Exception):
    """Outro processo segurou o lock durante todo o tempo de espera."""


def caminho_lock(indice: Path, nome: str = "ingestao") -> Path:
    """`<indice>.<nome>.lock` (ex.: `.docserver/indice.db.ingestao.lock`). O sufixo próprio
    evita colidir com arquivos `.lock` de outras ferramentas ao lado do índice."""
    indice = Path(indice)
    return indice.with_name(f"{indice.name}.{nome}.lock")


def _tentar(fd: int) -> bool:
    try:
        if sys.platform == "win32":
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _soltar(fd: int) -> None:
    try:
        if sys.platform == "win32":
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass


@contextmanager
def travar(
    caminho: Path,
    *,
    espera_s: float = 300.0,
    ao_aguardar: Callable[[], None] | None = None,
    intervalo_s: float = 0.2,
) -> Iterator[None]:
    """Segura o lock exclusivo sobre `caminho` (criado, com a pasta pai, se não existir).
    Tenta sem bloquear em laço até `espera_s`; `ao_aguardar` é chamado uma vez, na primeira
    falha. Esgotado o tempo, levanta `LockOcupado`. Sempre libera no `finally`."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(caminho, os.O_RDWR | os.O_CREAT)
    obtido = False
    try:
        limite = time.monotonic() + espera_s
        avisou = False
        while not (obtido := _tentar(fd)):
            if not avisou:
                avisou = True
                if ao_aguardar is not None:
                    ao_aguardar()
            if time.monotonic() >= limite:
                raise LockOcupado(f"lock ocupado por outro processo: {caminho}")
            time.sleep(intervalo_s)
        yield
    finally:
        if obtido:
            _soltar(fd)
        os.close(fd)

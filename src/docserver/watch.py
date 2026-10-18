"""`docserver watch`: observa docs-fonte e reingere sozinho quando algo muda."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from docserver import cli, extract

ESPERA_PADRAO = 2.0
INTERVALO_VERIFICACAO = 0.5
ESPERA_REVISAO_PADRAO = 10.0


def _log(mensagem: str) -> None:
    print(f"docserver: {mensagem}", flush=True)


class Agrupador:
    """Debounce: copiar uma pasta ou salvar um .docx gera dezenas de eventos; só
    vale reingerir quando passam `espera` segundos sem nenhum evento novo."""

    def __init__(self, espera: float, relogio=time.monotonic) -> None:
        self.espera = espera
        self._relogio = relogio
        self._lock = threading.Lock()
        self._pendente = False
        self._ultima_mudanca = 0.0
        self.eventos = 0

    def registrar(self) -> None:
        with self._lock:
            self._pendente = True
            self._ultima_mudanca = self._relogio()
            self.eventos += 1

    def pronto(self) -> bool:
        with self._lock:
            return self._pendente and self._relogio() - self._ultima_mudanca >= self.espera

    def consumir(self) -> int:
        """Zera a pendência e devolve quantos eventos ela acumulou. Eventos que chegarem
        depois (inclusive durante a ingestão) abrem uma pendência nova."""
        with self._lock:
            eventos = self.eventos
            self._pendente = False
            self.eventos = 0
            return eventos


def arquivo_relevante(caminho: str | bytes, docs_fonte: Path, padroes: tuple[str, ...] = ()) -> bool:
    """Só interessam arquivos que a ingestão de fato leria: descarta ocultos, os
    temporários `~$` do Office, pastas/arquivos de `ignorar` (ex.: `_pendentes`) e
    formatos sem extrator (inclusive `.tmp` de editores)."""
    arquivo = Path(os.fsdecode(caminho))
    return not cli._deve_ignorar(arquivo, docs_fonte, padroes) and arquivo.suffix.lower() in extract.EXTRATORES


def _pendente_para_revisar(caminho: str | bytes, pasta_pendentes: Path) -> bool:
    """`.md` não oculto (nem `~$`) direto em `pasta_pendentes` — o mesmo nível que o
    revisor lê; um arquivo em subpasta dispararia uma revisão que nunca o revisa."""
    arquivo = Path(os.path.abspath(os.fsdecode(caminho)))
    try:
        partes = arquivo.relative_to(Path(os.path.abspath(pasta_pendentes))).parts
    except ValueError:
        return False
    if len(partes) != 1 or partes[0].startswith((".", "~$")):
        return False
    return arquivo.suffix.lower() == ".md"


class _Manipulador(FileSystemEventHandler):
    def __init__(
        self,
        agrupador: Agrupador,
        docs_fonte: Path,
        padroes: tuple[str, ...] = (),
        agrupador_revisao: Agrupador | None = None,
        pasta_pendentes: Path | None = None,
    ) -> None:
        self._agrupador = agrupador
        self._docs_fonte = Path(docs_fonte)
        self._padroes = tuple(padroes)
        self._agrupador_revisao = agrupador_revisao
        self._pasta_pendentes = Path(pasta_pendentes) if pasta_pendentes is not None else None

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory or event.event_type in ("opened", "closed_no_write"):
            return
        if self._agrupador_revisao is not None and self._pasta_pendentes is not None:
            # só conta o que chega em pendentes: criado, modificado ou movido PARA lá
            # (aprovar move para fora e não deve disparar nova revisão)
            if event.event_type == "moved":
                alvo = getattr(event, "dest_path", "")
            elif event.event_type in ("created", "modified"):
                alvo = event.src_path
            else:
                alvo = ""
            if alvo and _pendente_para_revisar(alvo, self._pasta_pendentes):
                self._agrupador_revisao.registrar()
        caminhos = [event.src_path, getattr(event, "dest_path", "")]
        # renomear `rascunho.tmp` para `guia.md` só é relevante pelo destino, e
        # `guia.md` para `guia.bak` só pela origem — por isso vale qualquer um dos dois.
        if any(c and arquivo_relevante(c, self._docs_fonte, self._padroes) for c in caminhos):
            self._agrupador.registrar()


def _ingerir_e_relatar(
    docs_fonte: Path,
    docs_normalizado: Path,
    indice: str,
    sem_embeddings: bool,
    ignorar: tuple[str, ...] = (),
) -> None:
    relatorio = cli.executar_ingestao(
        docs_fonte, docs_normalizado, indice, sem_embeddings=sem_embeddings, ignorar=ignorar
    )
    print(cli.formatar_relatorio(relatorio), flush=True)


def _rodar_com_seguranca(ingerir_fn) -> None:
    """Uma ingestão que falha não pode derrubar o watcher: a próxima mudança (por
    exemplo, o arquivo terminar de ser copiado) tenta de novo."""
    try:
        ingerir_fn()
    except cli.ErroIngestao as erro:
        _log(f"ingestão abortada: {erro}")
    except Exception as erro:  # noqa: BLE001 — qualquer falha é registrada e o laço segue
        _log(f"erro inesperado na ingestão: {erro!r}")


def observar(
    docs_fonte: Path,
    docs_normalizado: Path,
    indice: str,
    sem_embeddings: bool = False,
    espera: float = ESPERA_PADRAO,
    ingerir_fn=None,
    parar: threading.Event | None = None,
    relogio=time.monotonic,
    ignorar: tuple[str, ...] = (),
    revisar: Callable[[], object] | None = None,
    pasta_pendentes: Path | None = None,
    espera_revisao: float = ESPERA_REVISAO_PADRAO,
) -> None:
    """Faz uma ingestão inicial (pega o que mudou com o watcher desligado) e depois
    reingere a cada lote de mudanças em `docs_fonte`, até `parar` ser acionado.

    Com `revisar` e `pasta_pendentes`, `.md` que aparecem em `pasta_pendentes` (criados,
    modificados ou movidos para lá) alimentam um segundo debounce (`espera_revisao`, maior
    porque o agente costuma escrever e depois editar) que chama `revisar()`. Esses eventos
    não disparam ingestão. Se já houver `.md` pendentes ao iniciar, revisa logo após a
    ingestão inicial. Revisão e ingestão rodam na mesma thread do laço, nunca juntas.

    `revisar` NÃO deve ingerir por conta própria: aprovar move o arquivo para a pasta de
    aprovados, e esse evento normal já dispara a ingestão pelo caminho de sempre."""
    if ingerir_fn is None:
        def ingerir_fn():
            _ingerir_e_relatar(docs_fonte, docs_normalizado, indice, sem_embeddings, ignorar)
    parar = parar or threading.Event()
    agrupador = Agrupador(espera, relogio=relogio)
    revisao_ativa = revisar is not None and pasta_pendentes is not None
    agrupador_revisao = Agrupador(espera_revisao, relogio=relogio) if revisao_ativa else None

    def revisar_agora() -> None:
        _log("revisando documentos pendentes…")
        _rodar_com_seguranca(revisar)

    # o observador sobe antes da ingestão inicial: o que mudar enquanto ela roda
    # vira uma pendência, em vez de se perder
    observador = Observer()
    observador.schedule(
        _Manipulador(agrupador, docs_fonte, ignorar, agrupador_revisao, pasta_pendentes),
        str(docs_fonte),
        recursive=True,
    )
    observador.start()
    try:
        _log("ingestão inicial")
        _rodar_com_seguranca(ingerir_fn)
        if revisao_ativa and any(
            _pendente_para_revisar(c, pasta_pendentes) for c in Path(pasta_pendentes).glob("*.md")
        ):
            revisar_agora()
        _log(f"observando {Path(docs_fonte).resolve()} (Ctrl+C para sair)")
        while not parar.wait(INTERVALO_VERIFICACAO):
            if agrupador.pronto():
                eventos = agrupador.consumir()
                _log(f"{eventos} mudança(s) detectada(s), reingerindo")
                _rodar_com_seguranca(ingerir_fn)
            if agrupador_revisao is not None and agrupador_revisao.pronto():
                agrupador_revisao.consumir()
                revisar_agora()
    finally:
        observador.stop()
        observador.join()

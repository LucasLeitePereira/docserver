import threading
import time
from pathlib import Path

import pytest
from watchdog.events import DirCreatedEvent, FileCreatedEvent, FileModifiedEvent, FileMovedEvent

from docserver import cli, index, watch


class RelogioFalso:
    def __init__(self):
        self.agora = 0.0

    def __call__(self):
        return self.agora


def test_agrupador_so_dispara_depois_da_espera_sem_eventos_novos():
    relogio = RelogioFalso()
    agrupador = watch.Agrupador(espera=2.0, relogio=relogio)
    assert not agrupador.pronto()

    agrupador.registrar()
    relogio.agora = 1.5
    assert not agrupador.pronto()

    agrupador.registrar()  # evento durante a espera reinicia a contagem
    relogio.agora = 3.0
    assert not agrupador.pronto()

    relogio.agora = 3.5
    assert agrupador.pronto()


def test_agrupador_rajada_de_eventos_vira_um_unico_disparo():
    relogio = RelogioFalso()
    agrupador = watch.Agrupador(espera=1.0, relogio=relogio)
    for _ in range(20):
        agrupador.registrar()

    relogio.agora = 1.0
    assert agrupador.pronto()
    assert agrupador.consumir() == 20
    assert not agrupador.pronto()


@pytest.mark.parametrize(
    "evento, relevante",
    [
        (FileModifiedEvent("docs-fonte/guia.md"), True),
        (FileCreatedEvent("docs-fonte/api/contrato.PDF"), True),
        (FileModifiedEvent("docs-fonte/~$relatorio.docx"), False),
        (FileModifiedEvent("docs-fonte/.oculto.md"), False),
        (FileCreatedEvent("docs-fonte/foto.png"), False),
        (DirCreatedEvent("docs-fonte/nova-pasta"), False),
        (FileMovedEvent("docs-fonte/rascunho.tmp", "docs-fonte/guia.md"), True),
        (FileMovedEvent("docs-fonte/guia.md", "docs-fonte/guia.bak"), True),
    ],
)
def test_manipulador_so_registra_arquivos_que_a_ingestao_leria(evento, relevante):
    agrupador = watch.Agrupador(espera=0)
    watch._Manipulador(agrupador, Path("docs-fonte")).dispatch(evento)
    assert agrupador.pronto() is relevante


@pytest.mark.parametrize(
    "evento, relevante",
    [
        (FileModifiedEvent("docs-fonte/_pendentes/x.md"), False),
        (FileCreatedEvent("docs-fonte/_pendentes/sub/y.md"), False),
        (FileModifiedEvent("docs-fonte/_revisoes.jsonl"), False),
        (FileMovedEvent("docs-fonte/_pendentes/x.md", "docs-fonte/conhecimento/x.md"), True),
        (FileMovedEvent("docs-fonte/conhecimento/x.md", "docs-fonte/_rejeitados/x.md"), True),
        (FileModifiedEvent("docs-fonte/conhecimento/x.md"), True),
        (FileModifiedEvent("docs-fonte/api/.rascunho/x.md"), False),
    ],
)
def test_manipulador_ignora_eventos_em_pastas_ignoradas(evento, relevante):
    agrupador = watch.Agrupador(espera=0)
    padroes = ("_pendentes", "_rejeitados", "_revisoes.jsonl")
    watch._Manipulador(agrupador, Path("docs-fonte"), padroes).dispatch(evento)
    assert agrupador.pronto() is relevante


def _rodar_em_thread(**kwargs):
    parar = threading.Event()
    thread = threading.Thread(target=watch.observar, kwargs={**kwargs, "parar": parar}, daemon=True)
    thread.start()
    return parar, thread


def _aguardar(condicao, prazo=10.0):
    limite = time.monotonic() + prazo
    while time.monotonic() < limite:
        if condicao():
            return True
        time.sleep(0.1)
    return False


def test_observar_faz_ingestao_inicial_e_segue_vivo_apos_erro(tmp_path):
    docs_fonte = tmp_path / "docs-fonte"
    docs_fonte.mkdir()
    chamadas = []

    def ingerir_falhando():
        chamadas.append(1)
        raise cli.ErroIngestao("simulado")

    parar, thread = _rodar_em_thread(
        docs_fonte=docs_fonte,
        docs_normalizado=tmp_path / "docs-normalizado",
        indice=str(tmp_path / "indice.db"),
        espera=0.1,
        ingerir_fn=ingerir_falhando,
    )
    try:
        assert _aguardar(lambda: len(chamadas) == 1)
        (docs_fonte / "guia.md").write_text("# Guia\n", encoding="utf-8")
        assert _aguardar(lambda: len(chamadas) >= 2)
        assert thread.is_alive()
    finally:
        parar.set()
        thread.join(timeout=5)
    assert not thread.is_alive()


def test_observar_indexa_arquivo_criado_depois_de_iniciado(tmp_path):
    docs_fonte = tmp_path / "docs-fonte"
    docs_normalizado = tmp_path / "docs-normalizado"
    docs_fonte.mkdir()
    docs_normalizado.mkdir()
    caminho_indice = str(tmp_path / "indice.db")

    parar, thread = _rodar_em_thread(
        docs_fonte=docs_fonte,
        docs_normalizado=docs_normalizado,
        indice=caminho_indice,
        sem_embeddings=True,
        espera=0.2,
    )
    try:
        time.sleep(0.5)  # deixa a ingestão inicial (vazia, abortada) passar
        (docs_fonte / "guia.md").write_text(
            "# Guia\n\n## Instalação\n\nRode o comando de setup para instalar o sistema.\n",
            encoding="utf-8",
        )
        # prazo folgado: a primeira ingestão do processo carrega o tokenizador do chunking
        assert _aguardar(lambda: index.contar_chunks(caminho_indice) > 0, prazo=60.0)
    finally:
        parar.set()
        thread.join(timeout=5)

    assert "instalar" in cli.formatar_resultados(cli.executar_busca(caminho_indice, "setup", modo="lexico"))


def test_parser_aceita_comando_watch():
    args = cli.construir_parser().parse_args(["watch", "--espera", "1", "--sem-embeddings"])
    assert args.func is cli._comando_watch
    assert args.espera == 1.0
    assert args.sem_embeddings


def test_comando_watch_com_fonte_inexistente_sai_com_erro(tmp_path, capsys):
    with pytest.raises(SystemExit) as saida:
        cli.main(["--docs-fonte", str(tmp_path / "nao-existe"), "--indice", str(tmp_path / "i.db"), "watch"])
    assert saida.value.code == 1
    assert "abortada" in capsys.readouterr().err.lower()


# --- revisão de pendentes ---------------------------------------------------


@pytest.mark.parametrize(
    "evento, revisa, ingere",
    [
        (FileCreatedEvent("docs-fonte/_pendentes/x.md"), True, False),
        (FileModifiedEvent("docs-fonte/_pendentes/y.MD"), True, False),
        # o revisor só lê o primeiro nível de _pendentes: subpasta não dispara revisão
        (FileModifiedEvent("docs-fonte/_pendentes/sub/y.md"), False, False),
        (FileMovedEvent("docs-fonte/rascunho.tmp", "docs-fonte/_pendentes/x.md"), True, False),
        (FileMovedEvent("docs-fonte/_pendentes/x.md", "docs-fonte/conhecimento/x.md"), False, True),
        (FileModifiedEvent("docs-fonte/_pendentes/.oculto.md"), False, False),
        (FileModifiedEvent("docs-fonte/_pendentes/nota.txt"), False, False),
        (FileModifiedEvent("docs-fonte/conhecimento/x.md"), False, True),
    ],
)
def test_manipulador_separa_eventos_de_revisao_e_ingestao(evento, revisa, ingere):
    ingestao = watch.Agrupador(espera=0)
    revisao = watch.Agrupador(espera=0)
    manipulador = watch._Manipulador(
        ingestao, Path("docs-fonte"), ("_pendentes",), revisao, Path("docs-fonte/_pendentes")
    )
    manipulador.dispatch(evento)
    assert revisao.pronto() is revisa
    assert ingestao.pronto() is ingere


def _preparar_revisao(tmp_path):
    docs_fonte = tmp_path / "docs-fonte"
    pendentes = docs_fonte / "_pendentes"
    pendentes.mkdir(parents=True)
    return docs_fonte, pendentes


def _iniciar_com_revisao(tmp_path, docs_fonte, pendentes, ingestoes, revisoes, revisar=None):
    def registrar_revisao():
        revisoes.append(1)

    return _rodar_em_thread(
        docs_fonte=docs_fonte,
        docs_normalizado=tmp_path / "docs-normalizado",
        indice=str(tmp_path / "indice.db"),
        espera=0.1,
        ingerir_fn=lambda: ingestoes.append(1),
        ignorar=("_pendentes",),
        revisar=revisar or registrar_revisao,
        pasta_pendentes=pendentes,
        espera_revisao=0.3,
    )


def test_observar_revisa_pendente_e_agrupa_edicoes_sem_ingerir(tmp_path):
    docs_fonte, pendentes = _preparar_revisao(tmp_path)
    ingestoes, revisoes = [], []
    parar, thread = _iniciar_com_revisao(tmp_path, docs_fonte, pendentes, ingestoes, revisoes)
    try:
        assert _aguardar(lambda: len(ingestoes) == 1)
        arquivo = pendentes / "nota.md"
        arquivo.write_text("# v1\n", encoding="utf-8")
        arquivo.write_text("# v2\n", encoding="utf-8")
        arquivo.write_text("# v3\n", encoding="utf-8")
        assert _aguardar(lambda: len(revisoes) >= 1)
        time.sleep(1.5)
        assert len(revisoes) == 1
        assert len(ingestoes) == 1
    finally:
        parar.set()
        thread.join(timeout=5)
    assert not thread.is_alive()


def test_observar_evento_fora_de_pendentes_ingere_e_nao_revisa(tmp_path):
    docs_fonte, pendentes = _preparar_revisao(tmp_path)
    ingestoes, revisoes = [], []
    parar, thread = _iniciar_com_revisao(tmp_path, docs_fonte, pendentes, ingestoes, revisoes)
    try:
        assert _aguardar(lambda: len(ingestoes) == 1)
        (docs_fonte / "guia.md").write_text("# Guia\n", encoding="utf-8")
        assert _aguardar(lambda: len(ingestoes) >= 2)
        time.sleep(1.0)
        assert revisoes == []
    finally:
        parar.set()
        thread.join(timeout=5)


def test_observar_ignora_oculto_e_nao_md_em_pendentes(tmp_path):
    docs_fonte, pendentes = _preparar_revisao(tmp_path)
    ingestoes, revisoes = [], []
    parar, thread = _iniciar_com_revisao(tmp_path, docs_fonte, pendentes, ingestoes, revisoes)
    try:
        assert _aguardar(lambda: len(ingestoes) == 1)
        (pendentes / ".oculto.md").write_text("x", encoding="utf-8")
        (pendentes / "nota.txt").write_text("x", encoding="utf-8")
        time.sleep(1.5)
        assert revisoes == []
        assert len(ingestoes) == 1
    finally:
        parar.set()
        thread.join(timeout=5)


def test_observar_pendentes_preexistentes_disparam_revisao_no_inicio(tmp_path):
    docs_fonte, pendentes = _preparar_revisao(tmp_path)
    (pendentes / "antigo.md").write_text("# antigo\n", encoding="utf-8")
    ordem = []
    parar, thread = _rodar_em_thread(
        docs_fonte=docs_fonte,
        docs_normalizado=tmp_path / "docs-normalizado",
        indice=str(tmp_path / "indice.db"),
        espera=0.1,
        ingerir_fn=lambda: ordem.append("ingestao"),
        ignorar=("_pendentes",),
        revisar=lambda: ordem.append("revisao"),
        pasta_pendentes=pendentes,
        espera_revisao=60.0,
    )
    try:
        assert _aguardar(lambda: len(ordem) >= 2)
        assert ordem[:2] == ["ingestao", "revisao"]
    finally:
        parar.set()
        thread.join(timeout=5)


def test_observar_excecao_em_revisar_nao_derruba_o_watcher(tmp_path, capsys):
    docs_fonte, pendentes = _preparar_revisao(tmp_path)
    ingestoes, chamadas = [], []

    def revisar_falhando():
        chamadas.append(1)
        raise RuntimeError("simulado")

    parar, thread = _iniciar_com_revisao(
        tmp_path, docs_fonte, pendentes, ingestoes, [], revisar=revisar_falhando
    )
    try:
        assert _aguardar(lambda: len(ingestoes) == 1)
        (pendentes / "a.md").write_text("# a\n", encoding="utf-8")
        assert _aguardar(lambda: len(chamadas) >= 1)
        assert thread.is_alive()
        (docs_fonte / "guia.md").write_text("# Guia\n", encoding="utf-8")
        assert _aguardar(lambda: len(ingestoes) >= 2)
        assert thread.is_alive()
    finally:
        parar.set()
        thread.join(timeout=5)
    assert not thread.is_alive()


def test_observar_sem_revisar_ignora_pendentes_como_antes(tmp_path):
    docs_fonte, pendentes = _preparar_revisao(tmp_path)
    ingestoes = []
    parar, thread = _rodar_em_thread(
        docs_fonte=docs_fonte,
        docs_normalizado=tmp_path / "docs-normalizado",
        indice=str(tmp_path / "indice.db"),
        espera=0.1,
        ingerir_fn=lambda: ingestoes.append(1),
        ignorar=("_pendentes",),
    )
    try:
        assert _aguardar(lambda: len(ingestoes) == 1)
        (pendentes / "a.md").write_text("# a\n", encoding="utf-8")
        time.sleep(1.5)
        assert len(ingestoes) == 1
    finally:
        parar.set()
        thread.join(timeout=5)

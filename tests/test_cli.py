import pytest

from docserver import cli


def _ingerir_um_documento(tmp_path):
    docs_fonte = tmp_path / "docs-fonte"
    docs_normalizado = tmp_path / "docs-normalizado"
    docs_fonte.mkdir()
    (docs_fonte / "guia.md").write_text(
        "# Guia\n\n## Instalação\n\nRode o comando de setup para instalar o sistema.\n",
        encoding="utf-8",
    )
    caminho_indice = str(tmp_path / "indice.db")
    cli.executar_ingestao(docs_fonte, docs_normalizado, caminho_indice, sem_embeddings=True)
    return docs_fonte, docs_normalizado, caminho_indice


def test_ingestao_com_docs_fonte_inexistente_aborta_sem_apagar_nada(tmp_path):
    _, docs_normalizado, caminho_indice = _ingerir_um_documento(tmp_path)

    with pytest.raises(cli.ErroIngestao):
        cli.executar_ingestao(tmp_path / "docs-fnote", docs_normalizado, caminho_indice, sem_embeddings=True)

    assert (docs_normalizado / "guia.md").exists()
    assert cli.executar_stats(caminho_indice)["chunks"] == 1


def test_ingestao_com_fonte_sem_arquivos_suportados_aborta_a_menos_que_forcar(tmp_path):
    docs_fonte, docs_normalizado, caminho_indice = _ingerir_um_documento(tmp_path)
    (docs_fonte / "guia.md").unlink()

    with pytest.raises(cli.ErroIngestao):
        cli.executar_ingestao(docs_fonte, docs_normalizado, caminho_indice, sem_embeddings=True)
    assert (docs_normalizado / "guia.md").exists()
    assert cli.executar_stats(caminho_indice)["chunks"] == 1

    cli.executar_ingestao(docs_fonte, docs_normalizado, caminho_indice, sem_embeddings=True, forcar=True)
    assert not (docs_normalizado / "guia.md").exists()
    assert cli.executar_stats(caminho_indice)["chunks"] == 0


def test_ingestao_que_nao_gera_chunks_nao_esvazia_indice_com_conteudo(tmp_path):
    docs_fonte, docs_normalizado, caminho_indice = _ingerir_um_documento(tmp_path)
    (docs_fonte / "guia.md").write_text("curto", encoding="utf-8")  # abaixo do mínimo de um chunk

    with pytest.raises(cli.ErroIngestao):
        cli.executar_ingestao(docs_fonte, docs_normalizado, caminho_indice, sem_embeddings=True)

    assert cli.executar_stats(caminho_indice)["chunks"] == 1


def test_limpeza_de_orfaos_preserva_md_que_nao_foi_gerado_pelo_docserver(tmp_path):
    docs_fonte, docs_normalizado, caminho_indice = _ingerir_um_documento(tmp_path)
    alheio = docs_normalizado / "anotacoes-pessoais.md"
    alheio.write_text("# Minhas anotações\n\nNão apague.\n", encoding="utf-8")

    relatorio = cli.executar_ingestao(docs_fonte, docs_normalizado, caminho_indice, sem_embeddings=True)

    assert alheio.exists()
    assert relatorio["preservados"] == [str(alheio)]
    assert relatorio["removidos"] == []


def test_comando_ingest_com_fonte_inexistente_e_limpar_sai_com_erro_sem_apagar(tmp_path, monkeypatch, capsys):
    _, docs_normalizado, caminho_indice = _ingerir_um_documento(tmp_path)

    with pytest.raises(SystemExit) as saida:
        cli.main(
            [
                "--docs-fonte",
                str(tmp_path / "nao-existe"),
                "--docs-normalizado",
                str(docs_normalizado),
                "--indice",
                caminho_indice,
                "ingest",
                "--limpar",
            ]
        )

    assert saida.value.code == 1
    assert "abortada" in capsys.readouterr().err.lower()
    assert (docs_normalizado / "guia.md").exists()
    assert cli.executar_stats(caminho_indice)["chunks"] == 1


def test_comando_ingest_limpar_so_remove_arquivos_gerados_pelo_docserver(tmp_path):
    docs_fonte, docs_normalizado, caminho_indice = _ingerir_um_documento(tmp_path)
    alheio = docs_normalizado / "anotacoes-pessoais.md"
    alheio.write_text("# Minhas anotações\n\nNão apague.\n", encoding="utf-8")

    cli.main(
        [
            "--docs-fonte",
            str(docs_fonte),
            "--docs-normalizado",
            str(docs_normalizado),
            "--indice",
            caminho_indice,
            "ingest",
            "--limpar",
            "--sem-embeddings",
        ]
    )

    assert alheio.exists()
    assert (docs_normalizado / "guia.md").exists()
    assert cli.executar_stats(caminho_indice)["chunks"] == 1


def test_fontes_com_mesmo_nome_e_extensoes_diferentes_nao_colidem(tmp_path):
    docs_fonte = tmp_path / "docs-fonte"
    docs_normalizado = tmp_path / "docs-normalizado"
    docs_fonte.mkdir()
    (docs_fonte / "manual.md").write_text(
        "# Manual MD\n\nConteúdo exclusivo da versão markdown do manual.\n", encoding="utf-8"
    )
    (docs_fonte / "manual.txt").write_text(
        "# Manual TXT\n\nConteúdo exclusivo da versão em texto puro do manual.\n", encoding="utf-8"
    )
    (docs_fonte / "manual.csv").write_text("coluna,valor\nversao,planilha\n", encoding="utf-8")
    caminho_indice = str(tmp_path / "indice.db")

    relatorio = cli.executar_ingestao(docs_fonte, docs_normalizado, caminho_indice, sem_embeddings=True)

    assert relatorio["processados"] == 3
    assert relatorio["falhas"] == []
    assert sorted(p.name for p in docs_normalizado.iterdir()) == ["manual.csv.md", "manual.md", "manual.txt.md"]
    assert cli.executar_stats(caminho_indice)["documentos"] == 3


def _embeddar_falso(chunk):
    texto = chunk["texto"]
    return [float(len(texto) % 7), float(len(texto) % 5), float(len(texto) % 3)]


def _embeddar_lote_falso(chunks):
    return [_embeddar_falso(c) for c in chunks]


def _embeddar_consulta_falso(consulta):
    return [float(len(consulta) % 7), float(len(consulta) % 5), float(len(consulta) % 3)]


def test_ingestao_processa_md_e_indexa_chunks(tmp_path):
    docs_fonte = tmp_path / "docs-fonte"
    docs_normalizado = tmp_path / "docs-normalizado"
    docs_fonte.mkdir()
    docs_normalizado.mkdir()
    (docs_fonte / "guia.md").write_text(
        "# Guia\n\n## Instalação\n\nRode o comando de setup para instalar o sistema.\n",
        encoding="utf-8",
    )
    caminho_indice = str(tmp_path / "indice.db")

    relatorio = cli.executar_ingestao(docs_fonte, docs_normalizado, caminho_indice, sem_embeddings=True)

    assert relatorio["processados"] == 1
    assert relatorio["chunks"] == 1
    assert (docs_normalizado / "guia.md").exists()


def test_ingestao_relatorio_conta_ignorados_e_falhas(tmp_path):
    docs_fonte = tmp_path / "docs-fonte"
    docs_normalizado = tmp_path / "docs-normalizado"
    docs_fonte.mkdir()
    docs_normalizado.mkdir()
    (docs_fonte / "guia.md").write_text("# Guia\n\nConteúdo.\n", encoding="utf-8")
    (docs_fonte / "planilha.xyz").write_text("formato não suportado", encoding="utf-8")
    caminho_indice = str(tmp_path / "indice.db")

    relatorio = cli.executar_ingestao(docs_fonte, docs_normalizado, caminho_indice, sem_embeddings=True)

    assert relatorio["processados"] == 1
    assert len(relatorio["ignorados"]) == 1


def test_ingestao_ignora_arquivos_ocultos_e_temporarios_do_office(tmp_path):
    docs_fonte = tmp_path / "docs-fonte"
    docs_normalizado = tmp_path / "docs-normalizado"
    docs_fonte.mkdir()
    docs_normalizado.mkdir()
    (docs_fonte / ".oculto.md").write_text("# Oculto\n\nConteúdo.\n", encoding="utf-8")
    (docs_fonte / "~$rascunho.docx").write_text("temporário do office", encoding="utf-8")
    (docs_fonte / "visivel.md").write_text("# Visível\n\nConteúdo com texto suficiente.\n", encoding="utf-8")
    caminho_indice = str(tmp_path / "indice.db")

    relatorio = cli.executar_ingestao(docs_fonte, docs_normalizado, caminho_indice, sem_embeddings=True)

    assert relatorio["processados"] == 1
    assert relatorio["ignorados"] == []


def test_busca_formata_resultado_com_origem_e_secao(tmp_path):
    docs_fonte = tmp_path / "docs-fonte"
    docs_normalizado = tmp_path / "docs-normalizado"
    docs_fonte.mkdir()
    docs_normalizado.mkdir()
    (docs_fonte / "guia.md").write_text(
        "# Guia\n\n## Instalação\n\nRode o comando de setup para instalar o sistema.\n",
        encoding="utf-8",
    )
    caminho_indice = str(tmp_path / "indice.db")
    cli.executar_ingestao(docs_fonte, docs_normalizado, caminho_indice, sem_embeddings=True)

    resultados = cli.executar_busca(caminho_indice, "instalar")
    texto = cli.formatar_resultados(resultados)

    assert "docs-fonte/guia.md" in texto
    assert "Instalação" in texto


def test_busca_sem_resultado_orienta_proximo_passo():
    texto = cli.formatar_resultados([])

    assert "listar_documentos" in texto or "reformular" in texto.lower()


def test_avaliar_calcula_taxa_de_acerto_por_perfil_no_modo_lexico(tmp_path):
    docs_fonte = tmp_path / "docs-fonte"
    docs_normalizado = tmp_path / "docs-normalizado"
    docs_fonte.mkdir()
    docs_normalizado.mkdir()
    (docs_fonte / "auth.md").write_text(
        "# Auth\n\n## Renovação\n\nO refresh token dura 30 dias e é rotacionado a cada uso.\n",
        encoding="utf-8",
    )
    caminho_indice = str(tmp_path / "indice.db")
    cli.executar_ingestao(docs_fonte, docs_normalizado, caminho_indice, sem_embeddings=True)

    caminho_perguntas = tmp_path / "perguntas.yaml"
    caminho_perguntas.write_text(
        "- pergunta: \"refresh token\"\n"
        "  esperado: docs-fonte/auth.md\n"
        "  perfil: tecnico\n"
        "- pergunta: \"algo que não existe em lugar nenhum\"\n"
        "  esperado: docs-fonte/auth.md\n"
        "  perfil: natural\n",
        encoding="utf-8",
    )

    resultado = cli.executar_avaliacao(caminho_perguntas, caminho_indice)

    assert resultado["lexico"]["tecnico"] == [1, 1]
    assert resultado["lexico"]["natural"] == [0, 1]


def test_ingestao_com_embeddings_grava_modelo_no_indice(tmp_path):
    docs_fonte = tmp_path / "docs-fonte"
    docs_normalizado = tmp_path / "docs-normalizado"
    docs_fonte.mkdir()
    docs_normalizado.mkdir()
    (docs_fonte / "guia.md").write_text(
        "# Guia\n\n## Seção\n\nConteúdo com bastante texto para não ser descartado.\n",
        encoding="utf-8",
    )
    caminho_indice = str(tmp_path / "indice.db")

    cli.executar_ingestao(
        docs_fonte,
        docs_normalizado,
        caminho_indice,
        embeddar_passagens_fn=_embeddar_lote_falso,
        nome_modelo="fake",
    )

    stats = cli.executar_stats(caminho_indice)
    assert stats["modelo"] == "fake"


def test_ingestao_com_sem_embeddings_nao_grava_modelo(tmp_path):
    docs_fonte = tmp_path / "docs-fonte"
    docs_normalizado = tmp_path / "docs-normalizado"
    docs_fonte.mkdir()
    docs_normalizado.mkdir()
    (docs_fonte / "guia.md").write_text(
        "# Guia\n\n## Seção\n\nConteúdo com bastante texto para não ser descartado.\n",
        encoding="utf-8",
    )
    caminho_indice = str(tmp_path / "indice.db")

    cli.executar_ingestao(docs_fonte, docs_normalizado, caminho_indice, sem_embeddings=True)

    stats = cli.executar_stats(caminho_indice)
    assert stats["modelo"] is None


def test_busca_com_modo_lexico_nao_usa_vetorial(tmp_path):
    docs_fonte = tmp_path / "docs-fonte"
    docs_normalizado = tmp_path / "docs-normalizado"
    docs_fonte.mkdir()
    docs_normalizado.mkdir()
    (docs_fonte / "guia.md").write_text(
        "# Guia\n\n## Seção\n\nConteúdo com bastante texto sobre faturamento mensal.\n",
        encoding="utf-8",
    )
    caminho_indice = str(tmp_path / "indice.db")
    cli.executar_ingestao(
        docs_fonte,
        docs_normalizado,
        caminho_indice,
        embeddar_passagens_fn=_embeddar_lote_falso,
        nome_modelo="fake",
    )

    resultados = cli.executar_busca(caminho_indice, "faturamento", modo="lexico")

    assert len(resultados) == 1


def test_avaliar_roda_nos_tres_modos_quando_indice_vetorial_existe(tmp_path):
    docs_fonte = tmp_path / "docs-fonte"
    docs_normalizado = tmp_path / "docs-normalizado"
    docs_fonte.mkdir()
    docs_normalizado.mkdir()
    (docs_fonte / "auth.md").write_text(
        "# Auth\n\n## Renovação\n\nO refresh token dura 30 dias e é rotacionado a cada uso.\n",
        encoding="utf-8",
    )
    caminho_indice = str(tmp_path / "indice.db")
    cli.executar_ingestao(
        docs_fonte,
        docs_normalizado,
        caminho_indice,
        embeddar_passagens_fn=_embeddar_lote_falso,
        nome_modelo="fake",
    )

    caminho_perguntas = tmp_path / "perguntas.yaml"
    caminho_perguntas.write_text(
        "- pergunta: \"refresh token\"\n"
        "  esperado: docs-fonte/auth.md\n"
        "  perfil: tecnico\n",
        encoding="utf-8",
    )

    resultado = cli.executar_avaliacao(
        caminho_perguntas,
        caminho_indice,
        modos=("lexico", "vetorial", "hibrido"),
        embeddar_consulta_fn=_embeddar_consulta_falso,
        nome_modelo="fake",
        dimensao=3,
    )

    assert set(resultado.keys()) == {"lexico", "vetorial", "hibrido"}
    assert resultado["lexico"]["tecnico"] == [1, 1]


def test_stats_reporta_documentos_e_chunks_indexados(tmp_path):
    docs_fonte = tmp_path / "docs-fonte"
    docs_normalizado = tmp_path / "docs-normalizado"
    docs_fonte.mkdir()
    docs_normalizado.mkdir()
    (docs_fonte / "guia.md").write_text(
        "# Guia\n\n## Seção\n\nConteúdo com bastante texto para não ser descartado.\n",
        encoding="utf-8",
    )
    caminho_indice = str(tmp_path / "indice.db")
    cli.executar_ingestao(docs_fonte, docs_normalizado, caminho_indice, sem_embeddings=True)

    stats = cli.executar_stats(caminho_indice)

    assert stats["documentos"] == 1
    assert stats["chunks"] == 1
    assert stats["modelo"] is None


def test_ingestao_remove_normalizado_orfao_quando_fonte_e_apagada(tmp_path):
    docs_fonte = tmp_path / "docs-fonte"
    docs_normalizado = tmp_path / "docs-normalizado"
    docs_fonte.mkdir()
    docs_normalizado.mkdir()
    origem = docs_fonte / "temporario.md"
    origem.write_text(
        "# Temporário\n\n## Seção\n\nConteúdo qualquer com texto suficiente para não ser descartado.\n",
        encoding="utf-8",
    )
    (docs_fonte / "permanente.md").write_text(
        "# Permanente\n\n## Seção\n\nDocumento que continua na fonte depois da remoção.\n",
        encoding="utf-8",
    )
    caminho_indice = str(tmp_path / "indice.db")
    cli.executar_ingestao(docs_fonte, docs_normalizado, caminho_indice, sem_embeddings=True)
    assert (docs_normalizado / "temporario.md").exists()

    origem.unlink()
    relatorio = cli.executar_ingestao(docs_fonte, docs_normalizado, caminho_indice, sem_embeddings=True)

    assert not (docs_normalizado / "temporario.md").exists()
    assert relatorio["removidos"] == [str(docs_normalizado / "temporario.md")]
    assert cli.executar_busca(caminho_indice, "temporário") == []


def test_busca_com_documento_restringe_ao_arquivo_indicado(tmp_path):
    docs_fonte = tmp_path / "docs-fonte"
    docs_normalizado = tmp_path / "docs-normalizado"
    docs_fonte.mkdir()
    docs_normalizado.mkdir()
    (docs_fonte / "a.md").write_text(
        "# Doc A\n\n## Prazo\n\nO prazo de entrega do documento A é de 10 dias.\n", encoding="utf-8"
    )
    (docs_fonte / "b.md").write_text(
        "# Doc B\n\n## Prazo\n\nO prazo de entrega do documento B é de 20 dias.\n", encoding="utf-8"
    )
    caminho_indice = str(tmp_path / "indice.db")
    cli.executar_ingestao(docs_fonte, docs_normalizado, caminho_indice, sem_embeddings=True)

    resultados = cli.executar_busca(caminho_indice, "prazo de entrega", origem="docs-fonte/b.md")

    assert len(resultados) == 1
    assert resultados[0]["caminho_origem"] == "docs-fonte/b.md"


def test_formatar_tabela_avaliacao_mostra_colunas_por_modo():
    resultado = {"lexico": {"tecnico": [9, 10], "natural": [3, 10]}}

    tabela = cli.formatar_tabela_avaliacao(resultado)

    assert "lexico" in tabela
    assert "9/10" in tabela
    assert "3/10" in tabela


def _projeto_com_config(tmp_path, monkeypatch, texto):
    (tmp_path / ".docserver.toml").write_text(texto, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path.resolve()


def _resolver(argv):
    args = cli.construir_parser().parse_args(argv)
    cli.resolver_configuracao(args, cli.config.carregar())
    return args


def test_precedencia_argumento_vence_arquivo_que_vence_padrao(tmp_path, monkeypatch):
    raiz = _projeto_com_config(tmp_path, monkeypatch, '[docs]\nfonte = "docs"\nindice = "x/i.db"\n')

    args = _resolver(["--docs-fonte", "explicito", "stats"])

    assert args.docs_fonte == "explicito"  # argumento
    assert args.indice == str(raiz / "x" / "i.db")  # arquivo
    assert args.docs_normalizado == str(raiz / "docs-normalizado")  # padrão, a partir da raiz do arquivo


def test_sem_arquivo_os_padroes_antigos_continuam(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    args = _resolver(["ingest"])

    assert args.docs_fonte == "docs-fonte"
    assert args.docs_normalizado == "docs-normalizado"
    assert args.indice == cli.INDICE_PADRAO.replace("/", "\\") or args.indice == cli.INDICE_PADRAO
    assert args.sem_embeddings is False
    assert args.ignorar == ()


def test_embeddings_false_no_arquivo_liga_sem_embeddings(tmp_path, monkeypatch):
    _projeto_com_config(tmp_path, monkeypatch, "[docs]\nembeddings = false\n")

    assert _resolver(["ingest"]).sem_embeddings is True
    assert _resolver(["watch"]).sem_embeddings is True


def test_serve_tambem_resolve_caminhos_do_arquivo(tmp_path, monkeypatch):
    raiz = _projeto_com_config(tmp_path, monkeypatch, '[docs]\nnormalizado = "n"\nindice = "i.db"\n')

    args = _resolver(["serve"])

    assert args.docs_normalizado == str(raiz / "n")
    assert args.indice == str(raiz / "i.db")


@pytest.mark.parametrize(
    "relativo, padroes, ignorado",
    [
        ("guia.md", (), False),
        (".oculto.md", (), True),
        ("api/.rascunho/x.md", (), True),
        (".git/config.md", (), True),
        ("api/~$relatorio.docx", (), True),
        ("_pendentes/x.md", ("_pendentes",), True),
        ("_pendentes/sub/y.md", ("_pendentes",), True),
        ("_pendentes/x.md", ("_pendentes/*",), True),
        ("_pendentes/x.md", (), False),
        ("conhecimento/x.md", ("_pendentes", "_rejeitados"), False),
        ("_revisoes.jsonl", ("_revisoes.jsonl",), True),
        ("conhecimento/_revisoes.jsonl", ("_revisoes.jsonl",), False),
    ],
)
def test_deve_ignorar_considera_o_caminho_relativo_a_docs_fonte(tmp_path, relativo, padroes, ignorado):
    assert cli._deve_ignorar(tmp_path / relativo, tmp_path, padroes) is ignorado


def test_deve_ignorar_fora_de_docs_fonte_olha_so_o_nome(tmp_path):
    docs_fonte = tmp_path / "docs"
    assert cli._deve_ignorar(tmp_path / ".oculta" / "x.md", docs_fonte) is False
    assert cli._deve_ignorar(tmp_path / ".x.md", docs_fonte) is True


def test_docs_fonte_em_pasta_oculta_nao_ignora_tudo_o_caminho_do_proprio_docs_fonte(tmp_path):
    # um docs_fonte dentro de uma pasta oculta não pode ignorar tudo
    docs_fonte = tmp_path / ".projeto" / "docs"
    assert cli._deve_ignorar(docs_fonte / "guia.md", docs_fonte) is False


def test_ingestao_ignora_pasta_pendentes(tmp_path):
    docs_fonte = tmp_path / "docs"
    (docs_fonte / "_pendentes").mkdir(parents=True)
    (docs_fonte / "conhecimento").mkdir()
    texto = "# Nota\n\n## Seção\n\nConteúdo suficiente para gerar um chunk indexável.\n"
    (docs_fonte / "_pendentes" / "rascunho.md").write_text(texto, encoding="utf-8")
    (docs_fonte / "conhecimento" / "ok.md").write_text(texto, encoding="utf-8")

    relatorio = cli.executar_ingestao(
        docs_fonte, tmp_path / "norm", str(tmp_path / "i.db"), sem_embeddings=True, ignorar=("_pendentes",)
    )

    assert relatorio["processados"] == 1
    assert not (tmp_path / "norm" / "_pendentes").exists()


def test_ingestao_com_lock_ocupado_aborta_sem_tocar_em_docs_normalizado(tmp_path):
    import subprocess
    import sys
    import time
    from pathlib import Path

    from docserver import lock

    docs_fonte = tmp_path / "docs-fonte"
    docs_fonte.mkdir()
    (docs_fonte / "guia.md").write_text("# Guia\n\nTexto suficiente para virar chunk.\n", encoding="utf-8")
    docs_normalizado = tmp_path / "docs-normalizado"
    caminho_indice = str(tmp_path / "indice.db")
    sinal = tmp_path / "sinal"
    script = (
        "import sys, time\nfrom pathlib import Path\nfrom docserver import lock\n"
        "with lock.travar(Path(sys.argv[1])):\n    Path(sys.argv[2]).write_text('x')\n    time.sleep(4)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script, str(lock.caminho_lock(Path(caminho_indice))), str(sinal)]
    )
    try:
        limite = time.monotonic() + 30
        while not sinal.exists():
            assert time.monotonic() < limite
            time.sleep(0.05)
        with pytest.raises(cli.ErroIngestao, match="outra ingestão"):
            cli.executar_ingestao(
                docs_fonte, docs_normalizado, caminho_indice, sem_embeddings=True, espera_lock_s=0.5
            )
        assert not docs_normalizado.exists()
    finally:
        proc.wait(timeout=30)


def test_comando_init_cria_arquivos_e_e_idempotente(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cli.main(["init", "--raiz", str(tmp_path / "proj")])
    assert (tmp_path / "proj" / ".docserver.toml").exists()
    cli.main(["init", "--raiz", str(tmp_path / "proj")])


def test_comando_init_funciona_com_toml_invalido(tmp_path):
    (tmp_path / ".docserver.toml").write_text("isto não é toml [[[", encoding="utf-8")
    cli.main(["init", "--raiz", str(tmp_path)])


# --- `docserver revisar` e a revisão no watcher -------------------------------------------

_REVISOR_FALSO = """
import json, sys
sys.stdin.read()
resposta = {"decisao": "aprovar", "motivos": ["explica o porquê"]}
print(json.dumps({"type": "result", "result": json.dumps(resposta), "total_cost_usd": 0.01}))
"""


def _projeto_com_pendente(tmp_path):
    import json
    import sys

    from docserver import init

    init.inicializar(tmp_path, modelo_revisor="modelo-revisor")
    revisor = tmp_path / "revisor_falso.py"
    revisor.write_text(_REVISOR_FALSO, encoding="utf-8")
    toml = tmp_path / ".docserver.toml"
    texto = toml.read_text(encoding="utf-8")
    inicio = texto.index("comando = [")
    fim = texto.index("]", inicio) + 1
    # string JSON é string básica válida em TOML (escapa as barras dos caminhos do Windows)
    comando = f"comando = [{json.dumps(sys.executable)}, {json.dumps(str(revisor))}]"
    toml.write_text(texto[:inicio] + comando + texto[fim:], encoding="utf-8")
    (tmp_path / "docs" / "_pendentes" / "wal.md").write_text(
        "---\ntitulo: Por que WAL\ntipo: decisao\ngerado_por: modelo-autor\n---\n\n"
        "# Por que WAL\n\nO watcher escreve enquanto o MCP lê; sem WAL o leitor trava.\n",
        encoding="utf-8",
    )
    return tmp_path


def test_revisar_sem_docserver_toml_sai_com_2(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as saida:
        cli.main(["revisar"])

    assert saida.value.code == 2
    assert "docserver init" in capsys.readouterr().out


def test_revisar_aprova_move_e_indexa(tmp_path, monkeypatch, capsys):
    raiz = _projeto_com_pendente(tmp_path)
    monkeypatch.chdir(raiz)

    with pytest.raises(SystemExit) as saida:
        cli.main(["revisar"])

    assert saida.value.code == 0
    aprovado = raiz / "docs" / "conhecimento" / "wal.md"
    assert aprovado.exists()
    assert not (raiz / "docs" / "_pendentes" / "wal.md").exists()
    assert "revisado_por: modelo-revisor" in aprovado.read_text(encoding="utf-8")
    resultados = cli.executar_busca(str(raiz / ".docserver" / "indice.db"), "watcher WAL", 5, modo="lexico")
    assert any("conhecimento/wal.md" in r["caminho_origem"] for r in resultados)


def test_revisar_com_outra_revisao_em_andamento_sai_com_1(tmp_path, monkeypatch, capsys):
    from docserver import lock

    raiz = _projeto_com_pendente(tmp_path)
    monkeypatch.chdir(raiz)

    with lock.travar(lock.caminho_lock(raiz / ".docserver" / "indice.db", "revisao")):
        with pytest.raises(SystemExit) as saida:
            cli.main(["revisar"])

    assert saida.value.code == 1
    assert (raiz / "docs" / "_pendentes" / "wal.md").exists()


def test_watch_liga_a_revisao_so_com_docserver_toml(tmp_path, monkeypatch):
    from docserver import watch

    chamadas = []
    monkeypatch.setattr(watch, "observar", lambda *a, **k: chamadas.append(k))

    monkeypatch.chdir(_projeto_com_pendente(tmp_path / "com"))
    cli.main(["watch"])
    sem = tmp_path / "sem"
    (sem / "docs-fonte").mkdir(parents=True)
    monkeypatch.chdir(sem)
    cli.main(["watch"])

    assert chamadas[0]["revisar"] is not None
    assert chamadas[0]["pasta_pendentes"].name == "_pendentes"
    assert chamadas[1]["revisar"] is None

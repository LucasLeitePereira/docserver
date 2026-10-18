import threading

import pytest

from docserver import embed


def test_texto_de_passagem_recebe_o_prefixo_passage():
    resultado = embed.preparar_passagem("conteúdo qualquer")

    assert resultado == "passage: conteúdo qualquer"


def test_texto_de_consulta_recebe_o_prefixo_query():
    resultado = embed.preparar_consulta("pergunta qualquer")

    assert resultado == "query: pergunta qualquer"


def test_texto_embeddado_concatena_titulo_secao_e_corpo():
    chunk = {
        "titulo_doc": "Contrato de API v2",
        "secao": "Limites de requisição",
        "texto": "O cliente pode fazer até 100 requisições por minuto.",
    }

    resultado = embed.texto_para_embeddar(chunk)

    assert resultado == (
        "Contrato de API v2 — Limites de requisição — "
        "O cliente pode fazer até 100 requisições por minuto."
    )


def test_modelo_e_carregado_uma_unica_vez(monkeypatch):
    chamadas = []

    def _carregador_falso():
        chamadas.append(1)
        return "modelo-falso"

    monkeypatch.setattr(embed, "_carregar_modelo", _carregador_falso)
    monkeypatch.setattr(embed, "_modelo_cache", None)

    embed.obter_modelo()
    embed.obter_modelo()

    assert len(chamadas) == 1


def test_chamadas_concorrentes_carregam_o_modelo_uma_unica_vez(monkeypatch):
    # aquecimento em thread + busca chegando no meio do carregamento
    chamadas = []
    carregando = threading.Event()
    liberar = threading.Event()

    def _carregador_lento():
        chamadas.append(1)
        carregando.set()
        liberar.wait(timeout=5)
        return "modelo-falso"

    monkeypatch.setattr(embed, "_carregar_modelo", _carregador_lento)
    monkeypatch.setattr(embed, "_modelo_cache", None)

    resultados = []
    aquecimento = threading.Thread(target=lambda: resultados.append(embed.obter_modelo()))
    aquecimento.start()
    assert carregando.wait(timeout=5)
    busca = threading.Thread(target=lambda: resultados.append(embed.obter_modelo()))
    busca.start()
    liberar.set()
    aquecimento.join(timeout=5)
    busca.join(timeout=5)

    assert len(chamadas) == 1
    assert resultados == ["modelo-falso", "modelo-falso"]


@pytest.mark.lento
def test_vetor_retornado_tem_a_dimensao_esperada_do_modelo():
    vetor = embed.embeddar_passagem({"titulo_doc": "Doc", "secao": "Sec", "texto": "Texto curto."})

    assert len(vetor) == embed.DIMENSAO


def test_embeddar_em_lote_chama_o_modelo_uma_vez_com_todos_os_textos(monkeypatch):
    chamadas = []

    class _ModeloFalso:
        def encode(self, textos, batch_size, normalize_embeddings):
            chamadas.append((list(textos), batch_size))
            import numpy

            return numpy.zeros((len(textos), 3))

    monkeypatch.setattr(embed, "_modelo_cache", _ModeloFalso())
    chunks = [{"texto": "um"}, {"texto": "dois"}]

    vetores = embed.embeddar_passagens(chunks, batch_size=8)

    assert chamadas == [(["passage: um", "passage: dois"], 8)]
    assert vetores == [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]


def test_embeddar_em_lote_sem_chunks_nao_carrega_o_modelo(monkeypatch):
    monkeypatch.setattr(embed, "_carregar_modelo", lambda: pytest.fail("não deveria carregar"))
    monkeypatch.setattr(embed, "_modelo_cache", None)

    assert embed.embeddar_passagens([]) == []


@pytest.mark.lento
def test_vetores_em_lote_iguais_aos_calculados_um_a_um():
    chunks = [
        {"titulo_doc": "Doc", "secao": "Sec", "texto": "Texto curto."},
        {"titulo_doc": "Outro", "secao": "Limites", "texto": "O cliente pode fazer até 100 requisições por minuto. " * 8},
    ]

    em_lote = embed.embeddar_passagens(chunks)
    um_a_um = [embed.embeddar_passagens([chunk])[0] for chunk in chunks]

    for vetor_lote, vetor_unico in zip(em_lote, um_a_um):
        assert max(abs(a - b) for a, b in zip(vetor_lote, vetor_unico)) < 1e-4

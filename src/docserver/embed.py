"""Embeddings de texto via sentence-transformers, com os prefixos exigidos pelo modelo e5."""

from __future__ import annotations

import threading

NOME_MODELO = "intfloat/multilingual-e5-small"
DIMENSAO = 384

_modelo_cache = None
# O servidor aquece o modelo numa thread enquanto já atende requisições: sem o lock,
# uma busca que chegasse durante o aquecimento carregaria uma segunda instância.
_lock_modelo = threading.Lock()


def _carregar_modelo():
    from sentence_transformers import SentenceTransformer

    # com o modelo já em cache, não consultar o Hugging Face Hub: a checagem de rede
    # soma segundos (ou trava sem rede) ao startup do servidor.
    try:
        return SentenceTransformer(NOME_MODELO, local_files_only=True)
    except Exception:
        return SentenceTransformer(NOME_MODELO)


def obter_modelo():
    """Carrega o modelo de embeddings uma única vez e reutiliza a instância."""
    global _modelo_cache
    if _modelo_cache is None:
        with _lock_modelo:
            if _modelo_cache is None:
                _modelo_cache = _carregar_modelo()
    return _modelo_cache


def preparar_passagem(texto: str) -> str:
    return f"passage: {texto}"


def preparar_consulta(texto: str) -> str:
    return f"query: {texto}"


def texto_para_embeddar(chunk: dict) -> str:
    """Concatena título, seção e corpo — dá contexto ao vetor de chunks curtos."""
    partes = [chunk.get("titulo_doc", ""), chunk.get("secao", ""), chunk.get("texto", "")]
    return " — ".join(parte for parte in partes if parte)


def embeddar_passagens(chunks: list[dict], batch_size: int = 1) -> list[list[float]]:
    """Vetores de uma lista de chunks numa única chamada ao modelo.

    O padrão `batch_size=1` é medido, não descuido: em CPU (4 threads), com chunks de
    ~330 tokens, 200 chunks levaram 25 s com lote 1 e 30 s com lote 32 — o custo está
    na atenção, não no overhead por chamada, e o lote só acrescenta padding. Em GPU,
    ou com chunks curtos, um lote maior tende a compensar."""
    if not chunks:
        return []
    modelo = obter_modelo()
    textos = [preparar_passagem(texto_para_embeddar(chunk)) for chunk in chunks]
    # normalizado para norma 1: permite converter a distância L2 do índice vetorial
    # em similaridade de cosseno com `sim = 1 - distancia**2 / 2` (ver index.py).
    return modelo.encode(textos, batch_size=batch_size, normalize_embeddings=True).tolist()


def embeddar_passagem(chunk: dict) -> list[float]:
    return embeddar_passagens([chunk])[0]


def embeddar_consulta(consulta: str) -> list[float]:
    modelo = obter_modelo()
    texto = preparar_consulta(consulta)
    return modelo.encode(texto, normalize_embeddings=True).tolist()

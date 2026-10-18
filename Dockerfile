FROM python:3.11-slim

ARG COM_EMBEDDINGS=true

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src
COPY avaliacao ./avaliacao

RUN if [ "$COM_EMBEDDINGS" = "true" ]; then \
        pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu ".[embeddings]"; \
    else \
        pip install --no-cache-dir .; \
    fi

# Cache do Hugging Face fora do HOME: o download abaixo roda como root, mas o
# servidor roda como `docserver` — com o cache padrão (~/.cache) ele não achava o
# modelo e, offline, a busca caía para só léxica.
ENV HF_HOME=/opt/huggingface

# Baixa o modelo de embeddings durante o build, não no primeiro uso — importante
# para o container não precisar de rede na primeira execução (ex.: demonstração).
RUN if [ "$COM_EMBEDDINGS" = "true" ]; then \
        python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-small')"; \
    fi

ENV HF_HUB_OFFLINE=1

RUN useradd --create-home --uid 1000 docserver \
    && mkdir -p /app/docs-fonte /app/docs-normalizado /app/data "$HF_HOME" \
    && chown -R docserver:docserver /app "$HF_HOME"
USER docserver

VOLUME ["/app/docs-fonte", "/app/docs-normalizado", "/app/data"]

CMD ["docserver", "serve"]

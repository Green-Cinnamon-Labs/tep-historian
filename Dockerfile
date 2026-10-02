# docker build -t tep-historian:latest .
# docker run --rm -p 8090:8090 tep-historian:latest
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir poetry && \
    poetry config virtualenvs.create false

# Dependências primeiro (cache de camada); o pacote em si é instalado depois de copiar src/
COPY pyproject.toml poetry.lock README.md ./
RUN poetry install --only main --no-root --no-interaction

COPY src/ src/
RUN poetry install --only main --no-interaction

EXPOSE 8090

ENV OPCUA_ENDPOINT=opc.tcp://host.docker.internal:4840/tep/server/
ENV SAMPLE_INTERVAL_MS=500
ENV RETENTION_S=3600
ENV PORT=8090

CMD ["python", "-m", "tep_historian"]

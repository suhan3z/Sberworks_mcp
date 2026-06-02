FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir .

RUN groupadd --system sberworks \
    && useradd --system --gid sberworks --home-dir /app sberworks \
    && mkdir -p /config /certs /attachments /app/.cert_cache \
    && chown -R sberworks:sberworks /app /config /certs /attachments

USER sberworks

ENTRYPOINT ["sberworks-mcp"]
CMD ["serve"]

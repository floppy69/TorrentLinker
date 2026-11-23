FROM python:3.12-slim
ARG TL_UID=1000
ARG TL_GID=1000
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TL_CONFIG_DIR=/config TL_WEB_HOST=0.0.0.0 TL_WEB_PORT=8787
RUN apt-get update && apt-get install -y --no-install-recommends libmediainfo0v5 ffmpeg unrar-free p7zip-full tini util-linux \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid ${TL_GID} torrentlinker \
    && useradd --uid ${TL_UID} --gid ${TL_GID} --create-home torrentlinker \
    && mkdir -m 700 /config && chown ${TL_UID}:${TL_GID} /config
WORKDIR /app
COPY pyproject.toml /app/
COPY src /app/src
COPY docs /app/docs
RUN pip install --no-cache-dir '.[web]'
USER torrentlinker
VOLUME ["/config"]
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/healthz', timeout=3)"
ENTRYPOINT ["python", "-m", "torrentlinker.container_entrypoint"]

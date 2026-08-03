# GDAL + Python geo stack. Base image ships GDAL and its Python bindings so the
# host (Mac mini / Colima) needs no system GDAL.
FROM ghcr.io/osgeo/gdal:ubuntu-small-3.9.2

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3-pip python3-dev build-essential \
        libspatialindex-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# --ignore-installed: the base image's numpy is a Debian package with no RECORD
# file, so pip can't uninstall it during dependency resolution. Ignoring installed
# packages sidesteps that and gives a consistent, PyPI-sourced environment.
RUN pip3 install --break-system-packages --ignore-installed -r requirements.txt

COPY pyproject.toml .
COPY src ./src
COPY assets ./assets
ENV MOOSE_SCOUT_ASSETS=/app/assets
RUN pip3 install --break-system-packages -e .

# config/ cache/ outputs/ are bind-mounted via docker-compose at runtime.
ENTRYPOINT ["moose-scout"]
CMD ["--help"]

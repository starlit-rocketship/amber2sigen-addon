# Overridden by CI's BUILD_FROM, but keep a sane default for local builds
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.21
FROM ${BUILD_FROM}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 1) Runtime deps + full build toolchain for Alpine
#    - build-base: meta (gcc, g++, make, musl-dev)
#    - python3-dev: headers for building C extensions
#    - libffi-dev, openssl-dev, linux-headers: common native deps
#    - cargo: rarely needed, but harmless if some transitive dep requires Rust
RUN apk add --no-cache \
    python3 py3-pip git \
    && apk add --no-cache --virtual .build-deps \
    build-base python3-dev libffi-dev openssl-dev linux-headers cargo

WORKDIR /opt/amber2sigen-addon

# 2) Upgrade pip/setuptools/wheel so musllinux wheels are recognized when available
RUN pip3 install --no-cache-dir --upgrade pip setuptools wheel

# 3) Install Python deps
COPY requirements.txt .
RUN pip3 install --no-cache-dir --prefer-binary -r requirements.txt

# 4) Pull upstream script (swap URL to your fork when you start modifying it)
RUN git clone --depth=1 https://github.com/Talie5in/amber2sigen.git /opt/amber2sigen

# 5) Add our wrapper and entrypoint
COPY status_mqtt.py ha_wrapper.py ./
COPY run.sh /run.sh
RUN chmod +x /run.sh

# 6) Remove build deps to slim the image
RUN apk del .build-deps

LABEL io.hass.name="Amber2Sigen" \
    io.hass.version="1.0.0" \
    io.hass.type="addon"

CMD ["/run.sh"]

# Overridden by CI's BUILD_FROM; default keeps local builds sane
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.21
FROM ${BUILD_FROM}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # ensure our venv python/pip come first
    PATH="/opt/venv/bin:${PATH}"

# Runtime deps + full build toolchain for Alpine
RUN apk add --no-cache \
    python3 py3-pip git \
    && apk add --no-cache --virtual .build-deps \
    build-base python3-dev libffi-dev openssl-dev linux-headers cargo

WORKDIR /opt/amber2sigen-addon

# Create an isolated venv to avoid PEP 668 issues
RUN python3 -m venv /opt/venv

# Upgrade pip/setuptools/wheel IN THE VENV, then install deps there
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir --prefer-binary -r requirements.txt

# Pull upstream (swap to your fork URL when you start modifying it)
RUN git clone --depth=1 https://github.com/Talie5in/amber2sigen.git /opt/amber2sigen

# Add our wrapper and entrypoint
COPY status_mqtt.py ha_wrapper.py ./
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Remove build deps to slim the image
RUN apk del .build-deps

LABEL io.hass.name="Amber2Sigen" \
    io.hass.version="1.0.0" \
    io.hass.type="addon"

CMD ["/run.sh"]

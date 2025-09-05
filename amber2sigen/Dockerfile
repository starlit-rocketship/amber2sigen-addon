# Overridden per-arch by your workflow's BUILD_FROM (e.g. amd64-base:3.21 / aarch64-base:3.21 / armv7-base:3.21)
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.21
FROM ${BUILD_FROM}

# Prefer venv python/pip and keep Python I/O unbuffered
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}"

# --- System deps ---
# - python3/py3-pip/git: runtime + fetch upstream
# - .build-deps: toolchain for compiling wheels on Alpine (removed later)
RUN apk add --no-cache \
    python3 py3-pip git \
    && apk add --no-cache --virtual .build-deps \
    build-base python3-dev libffi-dev openssl-dev linux-headers

WORKDIR /opt/amber2sigen-addon

# --- Python deps in isolated venv (avoids PEP 668) ---
RUN python3 -m venv /opt/venv
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir --prefer-binary -r requirements.txt

# --- Pull upstream (your fork by default; optionally pin a commit/tag) ---
ARG UPSTREAM_REPO=https://github.com/starlit-rocketship/amber2sigen.git
ARG UPSTREAM_REF=""
RUN git clone --depth=1 ${UPSTREAM_REPO} /opt/amber2sigen \
    && if [ -n "${UPSTREAM_REF}" ]; then \
    cd /opt/amber2sigen && git fetch --depth=1 origin ${UPSTREAM_REF} && git checkout ${UPSTREAM_REF}; \
    fi

# --- Add wrapper + entrypoint ---
COPY status_mqtt.py ha_entities_source.py sigen_push.py ./
COPY run.sh /run.sh
RUN chmod +x /run.sh

# --- Slim image ---
RUN apk del .build-deps

LABEL io.hass.name="Amber2Sigen" \
    io.hass.version="1.0.1" \
    io.hass.type="addon"

CMD ["/run.sh"]

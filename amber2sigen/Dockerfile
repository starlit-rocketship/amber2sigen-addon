# Pin is overridden by CI (BUILD_FROM build-arg), but keep a sane default
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.21
FROM ${BUILD_FROM}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Runtime deps + build deps for compiling wheels on Alpine (pycryptodome, etc.)
# We install build deps in a virtual package so we can remove them cleanly later.
RUN apk add --no-cache \
    python3 py3-pip git \
    && apk add --no-cache --virtual .build-deps \
    gcc musl-dev python3-dev libffi-dev openssl-dev linux-headers

WORKDIR /opt/amber2sigen-addon
COPY requirements.txt .

# Prefer wheels when available; otherwise compile (needs the build deps above)
RUN pip3 install --no-cache-dir --prefer-binary -r requirements.txt

# Fetch upstream script (swap to your fork URL if/when you start modifying it)
RUN git clone --depth=1 https://github.com/Talie5in/amber2sigen.git /opt/amber2sigen

# Copy wrappers/entrypoint
COPY status_mqtt.py ha_wrapper.py ./
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Clean up build deps to shrink image
RUN apk del .build-deps

LABEL io.hass.name="Amber2Sigen" \
    io.hass.version="1.0.0" \
    io.hass.type="addon"

CMD ["/run.sh"]

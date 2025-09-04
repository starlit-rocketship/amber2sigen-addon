# Home Assistant add-on base (S6 overlay, bashio ready).
# We'll pass BUILD_FROM from the HA builder or our GitHub Actions.
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.21
FROM ${BUILD_FROM}

# Make Python happy
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install deps
# - python3, pip, git for fetching upstream repo at build
# - tini is already in HA base (via s6), bashio available in base
RUN apk add --no-cache python3 py3-pip git

# Copy our add-on files
WORKDIR /opt/amber2sigen-addon
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Pull the upstream script at build time (pin to your fork/commit later if you want)
# You can swap to your fork URL when you start modifying upstream script:
#   https://github.com/starlit-rocketship/amber2sigen.git
RUN git clone --depth=1 https://github.com/Talie5in/amber2sigen.git /opt/amber2sigen

# Optional: copy our wrapper scripts
COPY status_mqtt.py ha_wrapper.py ./
# Runtime entrypoint
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Labels required if you're not using the HA builder, but nice to have anyway:
LABEL \
    io.hass.name="Amber2Sigen" \
    io.hass.version="1.0.0" \
    io.hass.type="addon" \
    io.hass.arch="amd64|aarch64|armv7"

CMD [ "/run.sh" ]

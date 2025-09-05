# ========== Base image comes from CI matrix ==========
ARG BUILD_FROM
FROM ${BUILD_FROM}

# ---------- Build args (cache-busting & upstream selection) ----------
ARG ADDON_VERSION=1.0.9
ARG UPSTREAM_REPO="https://github.com/starlit-rocketship/amber2sigen.git"
ARG UPSTREAM_REF=""  # set to a commit or tag to pin (optional)

# ---------- Environment ----------
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:${PATH}"

# Alpine shell with pipefail
SHELL ["/bin/ash", "-o", "pipefail", "-c"]

# ---------- System deps ----------
# python3, pip, git for runtime; build toolchain only for wheels compilation (pycryptodome, etc.)
RUN apk add --no-cache \
    python3 py3-pip git && \
    apk add --no-cache --virtual .build-deps \
    build-base python3-dev libffi-dev openssl-dev linux-headers cargo

# ---------- Workdir ----------
WORKDIR /opt/amber2sigen-addon

# ---------- Python deps ----------
# Keep requirements in the layer cache & install into an isolated venv (PEP 668 safe)
COPY requirements.txt ./
RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel && \
    /opt/venv/bin/pip install --no-cache-dir --prefer-binary -r requirements.txt

# ---------- Upstream script (your fork by default) ----------
# You can pin a specific ref (tag/commit) by setting UPSTREAM_REF in CI or locally.
RUN git clone --depth=1 "${UPSTREAM_REPO}" /opt/amber2sigen && \
    if [ -n "${UPSTREAM_REF}" ]; then \
    cd /opt/amber2sigen && \
    git fetch --depth=1 origin "${UPSTREAM_REF}" && \
    git checkout "${UPSTREAM_REF}"; \
    fi

# ---------- Add-on helpers ----------
# Copy ONLY files that exist in your repo under amber2sigen/
# (If you don't have ha_wrapper.py, do not list it here.)
COPY status_mqtt.py ha_entities_source.py sigen_push.py run.sh ./

# Ensure entrypoint is executable
RUN chmod +x /run.sh

# ---------- Clean up build deps ----------
RUN apk del .build-deps

# ---------- (Optional) quick debug of final contents (comment out after first success) ----------
# RUN echo "DEBUG: /opt/amber2sigen-addon contains:" && ls -la /opt/amber2sigen-addon

# ---------- Entrypoint ----------
CMD ["/run.sh"]

# OpenMuse cloud desktop image

FROM node:22-bookworm-slim AS node

FROM python:3.12-slim-bookworm

ARG APT_MIRROR=""
ARG PIP_INDEX_URL=""
ARG NPM_REGISTRY=""

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8

RUN if [ -n "$APT_MIRROR" ]; then \
        sed -i "s|deb.debian.org|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        xvfb openbox xdotool x11-utils \
        chromium fonts-noto-cjk fonts-noto-color-emoji \
        mousepad pcmanfm \
        x11vnc novnc websockify \
        bubblewrap socat ripgrep ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# tint2 taskbar
RUN apt-get update \
    && apt-get install -y --no-install-recommends tint2 adwaita-icon-theme \
    && rm -rf /var/lib/apt/lists/*

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && npm install -g ${NPM_REGISTRY:+--registry="$NPM_REGISTRY"} @anthropic-ai/sandbox-runtime \
    && npm cache clean --force

WORKDIR /opt/work-agent-sdk
COPY pyproject.toml README.md ./
COPY work_agent_sdk ./work_agent_sdk
RUN pip install --no-cache-dir ${PIP_INDEX_URL:+--index-url "$PIP_INDEX_URL"} . Pillow

COPY examples/showcase/openmuse/device/start-device.sh examples/showcase/openmuse/device/srt-settings.json \
     examples/showcase/openmuse/device/desktop-entrypoint.sh /opt/openmuse-device/
RUN chmod +x /opt/openmuse-device/*.sh \
    && useradd --create-home --shell /bin/bash muse

USER muse
WORKDIR /home/muse
ENV SCREEN_SIZE=1280x800x24
EXPOSE 6080
ENTRYPOINT ["/opt/openmuse-device/desktop-entrypoint.sh"]

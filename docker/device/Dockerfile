FROM python:3.12-slim

ARG BROWSER=0

RUN apt-get update \
    && apt-get install -y --no-install-recommends bubblewrap socat ripgrep nodejs npm ca-certificates \
    && npm install -g @anthropic-ai/sandbox-runtime \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/work-agent-sdk
COPY pyproject.toml README.md ./
COPY work_agent_sdk ./work_agent_sdk
RUN pip install --no-cache-dir .

RUN if [ "$BROWSER" = "1" ]; then \
        pip install --no-cache-dir playwright && playwright install --with-deps chromium; \
    fi

COPY docker/device/entrypoint.sh /usr/local/bin/work-agent-device
RUN chmod +x /usr/local/bin/work-agent-device && mkdir -p /workspace

ENV DEVICE_LISTEN=0.0.0.0:7000 \
    DEVICE_WORKSPACE=/workspace \
    DEVICE_SANDBOX=srt \
    DEVICE_AUDIT_LOG=/var/log/work-agent/audit.jsonl \
    PYTHONUNBUFFERED=1

WORKDIR /workspace
EXPOSE 7000
ENTRYPOINT ["work-agent-device"]

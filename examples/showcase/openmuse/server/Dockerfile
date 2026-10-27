FROM python:3.12-slim-bookworm

ARG PIP_INDEX_URL=""

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OPENMUSE_DATA_DIR=/data

WORKDIR /opt/work-agent-sdk
COPY pyproject.toml README.md ./
COPY work_agent_sdk ./work_agent_sdk
COPY examples/showcase/openmuse/server/requirements.txt /tmp/requirements.txt
RUN pip install ${PIP_INDEX_URL:+--index-url "$PIP_INDEX_URL"} . -r /tmp/requirements.txt

WORKDIR /app
COPY examples/showcase/openmuse/server/main.py ./
COPY examples/showcase/openmuse/server/openmuse ./openmuse

VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

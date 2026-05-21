# syntax=docker/dockerfile:1.7
FROM docker.m.daocloud.io/python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/AgentServer:/app/DataSync \
    DATASYNC_RUNTIME_DIR=/app/DataSync \
    DATASYNC_DATA_DIR=/app/DataSync/data \
    OBS_LOG_DIR=/app/DataSync/logs \
    MILVUS_URI=/app/DataSync/data/milvus_lite.db \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g; s|security.debian.org|mirrors.tuna.tsinghua.edu.cn/debian-security|g' /etc/apt/sources.list.d/debian.sources

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY AgentServer/requirements.txt /tmp/requirements.txt

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /tmp/requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --trusted-host pypi.tuna.tsinghua.edu.cn

COPY AgentServer/ /app/AgentServer/
COPY DataSync/ /app/DataSync/

WORKDIR /app/DataSync

RUN mkdir -p /app/DataSync/logs /app/DataSync/data

CMD ["python", "main.py"]

# One image for laptop (x86_64) and Raspberry Pi (aarch64, 64-bit OS).
# Motion and the Python "brain" run in the same container (see scripts/entrypoint.sh).
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        motion \
        espeak-ng \
        pulseaudio-utils \
        alsa-utils \
        openssh-client \
        libnss-wrapper \
        curl \
        ca-certificates \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --no-deps openwakeword==0.6.0

# Models are baked into the image so nothing is downloaded at runtime.
COPY scripts/download_models.sh scripts/
RUN sh scripts/download_models.sh /app/models \
    && chmod -R a+rX /app/models

# Claude Code, for CLAUDE_BACKEND=cli (runs `claude -p` on your Claude subscription).
# Pinned so the robot doesn't change behaviour on its own; bump deliberately.
ARG CLAUDE_CODE_VERSION=2.1.304
RUN curl -fsSL https://claude.ai/install.sh | bash -s "$CLAUDE_CODE_VERSION" \
    && cp -L /root/.local/bin/claude /usr/local/bin/claude \
    && rm -rf /root/.local/share/claude /root/.local/bin/claude \
    && claude --version
ENV DISABLE_AUTOUPDATER=1

COPY . .
RUN chmod +x scripts/*.sh

ENV PYTHONUNBUFFERED=1 \
    HF_HUB_OFFLINE=1 \
    ROBOT_DATA_DIR=/data \
    ROBOT_MODELS_DIR=/app/models \
    HOME=/tmp

EXPOSE 8080 8081
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["run"]

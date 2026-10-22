# Pre-Warmed Agni Sandbox Container
FROM python:3.12-slim-bookworm

# Install core build and developer tools (Node, Git, Ripgrep, Pyright)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    ripgrep \
    build-essential \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g pyright typescript \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Keep container alive and pre-warmed for instant `docker exec` execution
CMD ["tail", "-f", "/dev/null"]

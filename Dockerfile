# Lightweight runtime image for Nova's terminal agent.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/nova

WORKDIR /opt/nova

# Git is needed by Nova's local Git integration. Keep the base image small.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY . /opt/nova

# Keep application code root-owned. The episodic-memory module currently stores
# its JSON data beside the module, so only that package directory is writable.
RUN useradd --create-home --uid 10001 nova \
    && mkdir -p /workspace/projects /workspace/memory \
    && chown -R nova:nova /workspace \
    && chmod 755 /opt/nova

WORKDIR /workspace
USER nova

CMD ["python", "/opt/nova/main.py", "--prompt-toolkit"]

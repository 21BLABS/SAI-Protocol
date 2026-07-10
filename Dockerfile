# SAI Protocol — Agent Enclave Dockerfile
# -----------------------------------------
# This image runs inside the Phala dStack TEE. Its SHA256 digest becomes
# the composeHash registered in SoulAccount. Pin every dependency to an
# exact version — any change to the image changes the hash, which is the
# intended tamper-evidence behavior.

FROM python:3.11.9-slim

# Non-root user for principle of least privilege inside the enclave
RUN groupadd -r agent && useradd -r -g agent agent

WORKDIR /app

# Install system deps first (layer cached unless these change)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python deps before copying source code.
# This means a code change doesn't invalidate the dep cache layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent source
COPY enclave/ ./enclave/
COPY agent/   ./agent/

# Switch to non-root
USER agent

# Health check endpoint (checked by dStack before accepting attestations)
EXPOSE 8080

# Entrypoint: the key manager runs first (generates key + attests),
# then the main agent loop starts. They run in the same process via
# the orchestrator which manages both as threads.
CMD ["python", "-m", "enclave.orchestrator"]

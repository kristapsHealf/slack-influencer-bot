# syntax=docker/dockerfile:1

#### Stage 1: install dependencies ####
FROM python:3.11-slim AS builder

# Install system deps needed by Poetry and your packages
RUN apt-get update && \
    apt-get install -y \
    curl \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

# Copy lockfiles and install only runtime deps
COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false \
 && poetry install --no-dev --no-interaction --no-ansi

#### Stage 2: build final image ####
FROM python:3.11-slim

# Install runtime system dependencies
RUN apt-get update && \
    apt-get install -y \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy Poetry (and system deps) from builder
COPY --from=builder /root/.local /root/.local
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

# Copy source code
COPY src/ ./src/

# Expose a port if you add a health check HTTP server (optional)
# EXPOSE 8080

# Launch the bot in Socket Mode
CMD ["poetry", "run", "python", "src/bot.py"]

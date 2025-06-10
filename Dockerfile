# syntax=docker/dockerfile:1

#### Stage 1: install dependencies ####
FROM python:3.11-slim AS builder

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

# Copy lockfiles and install dependencies
COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false \
 && poetry install --without dev --no-root --no-interaction --no-ansi

#### Stage 2: build final image ####
FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed packages from builder stage
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy source code
COPY src/ ./src/

CMD ["python", "src/bot.py"]
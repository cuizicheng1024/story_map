# Stage 1: Build dependencies (leverages Docker layer caching)
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies with cache mount for faster rebuilds
COPY requirements.txt ./requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
    && pip install -r requirements.txt

# Stage 2: Runtime image
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8765

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy only runtime-necessary application files
COPY storymap/ ./storymap/
COPY data/ ./data/
COPY artifacts/ ./artifacts/
COPY tools/build/ ./tools/build/
COPY requirements.txt ./requirements.txt

EXPOSE 8765

# 使用 exec 确保信号正确传递到 Python 进程
CMD ["sh", "-c", "exec python3 storymap/script/story_map.py --serve --port ${PORT:-8765}"]

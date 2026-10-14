FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 先装依赖（利用 Docker 层缓存），再拷代码
# openssh-client：串行控制台（/ws/console）桥接依赖 ssh 二进制
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir . \
    && mkdir -p /app/data

EXPOSE 8818

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8818"]

# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /code

# Install with pip (not the uv binary): Container Apps needs linux/amd64, so on
# Apple Silicon the image builds under QEMU emulation — where the uv Rust binary
# segfaults but pip (pure Python) works. requirements.txt is generated from the
# lockfile: `uv export --no-dev --no-hashes --no-emit-project -o requirements.txt`
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

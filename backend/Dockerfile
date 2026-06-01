FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml requirements-ocr.txt ./
COPY app ./app

ARG INSTALL_OCR=false
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install . \
    && if [ "$INSTALL_OCR" = "true" ]; then python -m pip install -r requirements-ocr.txt; fi

COPY alembic ./alembic
COPY alembic.ini main_fastapi.py seed_data.py ./
COPY scripts ./scripts
COPY uploads ./uploads

EXPOSE 5000

CMD ["uvicorn", "main_fastapi:app", "--host", "0.0.0.0", "--port", "5000"]

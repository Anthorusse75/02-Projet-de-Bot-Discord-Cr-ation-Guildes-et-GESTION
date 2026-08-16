FROM python:3.13.14-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY backend ./backend
RUN pip install --no-cache-dir uv==0.12.5 && uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "did.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

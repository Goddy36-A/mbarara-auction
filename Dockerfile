FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source — any change here invalidates this layer and everything below
COPY . .

# collectstatic needs SECRET_KEY; provide a dummy at build time only.
# ALLOWED_HOSTS is not needed for collectstatic so we leave it empty.
RUN SECRET_KEY=build-time-placeholder \
    DJANGO_SETTINGS_MODULE=config.settings.production \
    python manage.py collectstatic --noinput || true

EXPOSE 8000

# Render injects PORT; gunicorn binds to it.
CMD ["sh", "-c", "gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 120"]

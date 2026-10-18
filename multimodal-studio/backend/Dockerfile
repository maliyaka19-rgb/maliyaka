# backend/Dockerfile - Python FastAPI container (ücretsiz hosting uyumlu)

FROM python:3.11-slim

WORKDIR /app

# Sistem bağımlılıkları
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python bağımlılıkları (katman önbelleği için önce yalnızca gereksinimler)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Uygulamanın TAMAMI kopyalanır (eskiden yalnızca app.py kopyalanıyordu;
# bu yüzden konteyner tüm modüller olmadan çalışamıyordu).
COPY . .

# Yazılabilir veri klasörleri (öğrenme kaydı, beyin, üretilen videolar)
RUN mkdir -p brain_data learning_registry generated_videos auth_data \
    && useradd -m appuser \
    && chown -R appuser:appuser /app

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

USER appuser

# Port, platformun verdiği $PORT'tan okunur; yoksa 8000.
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Yerevan
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot ./bot
COPY config/clinic.example.yaml ./config/clinic.example.yaml

# config/clinic.yaml, .env, secrets/ and data/ are mounted at run time (see docker-compose.yml)
RUN useradd -m botuser && mkdir -p /app/data && chown -R botuser /app
USER botuser
CMD ["python", "-m", "bot.main"]

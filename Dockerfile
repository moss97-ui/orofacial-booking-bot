FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Yerevan
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot ./bot
COPY config/clinic.example.yaml ./config/
# English / Russian translations (only used when the config lists more than one language)
COPY i18n ./i18n

# config/clinic.yaml, .env, secrets/ and data/ are mounted at run time (see docker-compose.yml).
# On Railway they come from variables instead (see README, "Deploy on Railway").
RUN useradd -m botuser && mkdir -p /app/data && chown -R botuser /app
USER botuser
CMD ["python", "-m", "bot.main"]

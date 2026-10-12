FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home bot
COPY narrative_bot narrative_bot
RUN mkdir /data && chown bot:bot /data
USER bot
ENV DATABASE_PATH=/data/game.sqlite3 PYTHONUNBUFFERED=1
VOLUME ["/data"]
CMD ["python", "-m", "narrative_bot"]

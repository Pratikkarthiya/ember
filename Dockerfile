FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    EMBER_DATABASE=/data/ember.sqlite3

WORKDIR /app
COPY app.py menu.json ./
COPY static ./static
RUN mkdir -p /data && useradd --system --uid 10001 ember && chown ember /data
USER ember
EXPOSE 8000
VOLUME ["/data"]
CMD ["sh", "-c", "exec python app.py --host 0.0.0.0 --port \"${PORT}\""]

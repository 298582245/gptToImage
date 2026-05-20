FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN adduser --disabled-password --gecos "" appuser
COPY --chown=appuser:appuser . .

RUN mkdir -p /app/generated /app/data && chown -R appuser:appuser /app/generated /app/data

USER appuser

EXPOSE 8090

CMD ["gunicorn", "-w", "1", "-k", "gthread", "--threads", "4", "--timeout", "900", "--graceful-timeout", "120", "-b", "0.0.0.0:8090", "app:app"]

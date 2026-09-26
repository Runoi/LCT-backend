FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY pytest.ini ./pytest.ini
COPY tests ./tests
COPY data ./data

EXPOSE 8000

# --proxy-headers: the real client IP comes from the TLS proxy (X-Forwarded-For is set, not appended, by nginx).
# Trusting any forwarder is safe only because this port is not published outside the compose network.
CMD ["sh", "-c", "alembic upgrade head && uvicorn src.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips '*'"]

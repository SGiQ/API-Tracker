# Container image for the API-Tracker ingest service.
# Railway prioritizes a Dockerfile over its Railpack/Nixpacks builders, so this
# makes the build deterministic regardless of the platform's default builder.

FROM python:3.12-slim

WORKDIR /app
COPY . .

# Install the package plus the [server] extra (FastAPI + uvicorn).
RUN pip install --no-cache-dir ".[server]"

# Railway injects $PORT; `apitracker serve` binds 0.0.0.0:$PORT and reads
# $APITRACKER_DSN for the Postgres connection.
CMD ["apitracker", "serve"]

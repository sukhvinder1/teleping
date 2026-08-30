FROM python:3.12-slim

RUN pip install --no-cache-dir "mcp>=2,<3"

WORKDIR /app
COPY tg_mcp.py .

# Cloud Run provides $PORT; MCP_PATH_SECRET and BOTS_GCS_BUCKET come from
# the service's env vars.
CMD ["python3", "tg_mcp.py"]

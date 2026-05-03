FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY services/test-platform-mcp ./services/test-platform-mcp

RUN pip install -e ./services/test-platform-mcp

ENV TEST_PLATFORM_API_URL=http://api:8000
ENV TEST_PLATFORM_MCP_HOST=0.0.0.0
ENV TEST_PLATFORM_MCP_PORT=8765
ENV TEST_PLATFORM_MCP_TRANSPORT=sse

EXPOSE 8765

CMD ["python", "-m", "test_platform_mcp.server"]

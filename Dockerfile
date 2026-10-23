FROM python:3.12-slim

WORKDIR /app
ARG ENGINE_REVISION=unversioned
ENV ENGINE_VERSION=$ENGINE_REVISION

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py storage.py admin_panel.py integration_api.py user_setup.py conversation_context.py ./
COPY templates ./templates

CMD ["python", "bot.py"]

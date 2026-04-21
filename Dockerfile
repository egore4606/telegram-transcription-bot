FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py storage.py admin_panel.py ./
COPY templates ./templates

CMD ["python", "bot.py"]

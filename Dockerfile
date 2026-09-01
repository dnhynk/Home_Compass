FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME_COMPASS_ENV=production \
    HOME_COMPASS_COOKIE_SECURE=true \
    HOME_COMPASS_STORE_URL=sqlite:///var/data/home_compass.db \
    HOME_COMPASS_LOG_FILE=/var/data/observability.jsonl

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN python -m pip install --no-cache-dir -r /app/backend/requirements.txt

COPY . /app
RUN mkdir -p /var/data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import json,os,urllib.request; p=os.environ.get('PORT','8000'); r=urllib.request.urlopen('http://127.0.0.1:'+p+'/api/health', timeout=4); assert r.status == 200 and json.load(r)['status'] == 'ok'"

CMD ["python", "scripts/start_server.py"]

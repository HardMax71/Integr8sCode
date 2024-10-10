FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app /app/app
COPY .env /app/.env
COPY kubeconfig.yaml /app/kubeconfig.yaml

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
FROM --platform=$TARGETPLATFORM python:3.12-slim

ARG TARGETPLATFORM

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY static/ static/

ENV GRID_DATA_DIR=/data
ENV GRID_KEYS_DIR=/data/keys

RUN mkdir -p /data/keys

EXPOSE 8501

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8501"]

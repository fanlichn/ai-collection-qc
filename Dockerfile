FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04 AS base
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip ffmpeg libgomp1 ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/app
COPY requirements.txt .
RUN python3 -m pip install --upgrade pip && python3 -m pip install -r requirements.txt
RUN mkdir -p /data/audio

FROM base AS worker
RUN python3 -m pip install --index-url https://download.pytorch.org/whl/cu124 torch==2.6.0
RUN python3 -m pip install qwen-asr==0.0.6 'python-dateutil<3'
COPY app ./app
CMD ["python3","-m","app.worker"]

FROM base AS api
COPY app ./app
COPY web ./web
EXPOSE 8080
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8080"]

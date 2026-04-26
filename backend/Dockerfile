# Official image via AWS Public ECR mirror avoids Docker Hub rate limits.
FROM public.ecr.aws/docker/library/python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    cmake \
    ffmpeg \
    git \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git /opt/whisper.cpp \
    && cmake -S /opt/whisper.cpp -B /opt/whisper.cpp/build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /opt/whisper.cpp/build --config Release -j "$(nproc)"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /data/uploads /data/transcripts /models

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

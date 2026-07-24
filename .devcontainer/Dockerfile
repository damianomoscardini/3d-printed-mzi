FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    tzdata \
    python3-tk \
    libxext6 \
    libxrender1 \
    libxtst6 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    pyvisa \
    pyvisa-py \
    matplotlib \
    tzdata

WORKDIR /workspace

CMD ["/bin/bash"]
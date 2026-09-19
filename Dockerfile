FROM python:3.11.14-slim-bookworm AS common
WORKDIR /workspace
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TEMP=/workspace/.runtime/tmp \
    TMPDIR=/workspace/.runtime/tmp
RUN mkdir -p .runtime/tmp && apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements/ requirements/
RUN python -m pip install --no-cache-dir --require-hashes -r requirements/app.lock \
    && python -m pip check
COPY app/ app/
COPY scripts/ scripts/
COPY samples/ samples/
COPY tests/ tests/
COPY pyproject.toml ./
CMD ["python", "-m", "app.cli", "--help"]

FROM common AS cpu
ENV PADDLEOCR_DEVICE=cpu
RUN python -m pip install --no-cache-dir --require-hashes -r requirements/ocr-cpu.lock \
    && python -m pip check

FROM common AS gpu
ENV PADDLEOCR_DEVICE=gpu:0 \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility
RUN python -m pip install --no-cache-dir -r requirements/ocr-gpu-cu129.txt \
    && python -m pip check

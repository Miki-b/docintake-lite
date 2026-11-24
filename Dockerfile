# DocIntake Lite — Hugging Face Spaces (Docker SDK).
# OCR is torch + python-doctr on CPU, so we install the CPU-only torch wheel
# (avoids the multi-GB CUDA build) and bake the doctr weights into the image
# for a fast, offline cold start.

FROM python:3.11-slim

# System libs doctr/opencv need at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# HF Spaces runs the container as uid 1000; match it so build-time downloads
# (weights, caches) are owned by the runtime user and persist into the image.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    DOCTR_CACHE_DIR=/home/user/.cache/doctr \
    TORCH_HOME=/home/user/.cache/torch \
    HF_HOME=/home/user/.cache/huggingface

WORKDIR /home/user/app

# CPU-only torch first so the doctr dependency resolves against it (not CUDA).
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY --chown=user:user requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user:user . .

# Pre-download OCR weights and generate the synthetic sample PDFs at build time.
RUN python -c "from app.ocr import _doctr_model; _doctr_model()" \
    && python scripts/make_samples.py

EXPOSE 7860
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "7860"]

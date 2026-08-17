FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM python:3.11-slim AS runtime
WORKDIR /app/backend

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
# CPU-only torch first: sentence-transformers pulls torch, which otherwise
# resolves to the CUDA build (multiple GB of unused NVIDIA packages) even
# on a CPU-only host like Render's web service.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

# The cross-encoder is a ~470 MB HuggingFace download. Left to runtime it lands
# on the first query after every deploy and every cold start -- on the critical
# path of a user's question. Baking it in moves that to build time. HF_HOME is
# set before the download and persists into the running image, so the runtime
# finds the same cache. The model name is read from config rather than repeated
# here, so it cannot drift from settings.reranker_model.
ENV HF_HOME=/opt/huggingface
RUN python -c "from config import settings; from sentence_transformers import CrossEncoder; CrossEncoder(settings.reranker_model)"

COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

EXPOSE 8000
# One worker deliberately. Each worker holds its own copy of the loaded corpus
# and the cross-encoder (~1.2 GB measured with one corpus resident), so a second
# one does not fit on the configured instance.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]

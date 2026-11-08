FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AAC_EMBED_CACHE_DIR=/opt/embed-models \
    AAC_LOCAL_EMBED_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# 로컬 임베딩 모델을 이미지 빌드 때 받아 둔다(약 230MB, 양자화 ONNX). 실행 중에는 내려받지 않는다 —
# 아래 HF_HUB_OFFLINE=1이라 네트워크가 막힌 운영 환경에서도 같은 모델로 뜬다. 모델을 바꾸려면
# 빌드 인자 대신 AAC_LOCAL_EMBED_MODEL을 고치고 다시 빌드한 뒤 scripts/build_aac_embeddings.py로
# data/aac/aac_embeddings.npz도 다시 만든다(모델이 다르면 서비스가 자산 벡터를 쓰지 않는다).
RUN python -c "import os; from fastembed import TextEmbedding; \
TextEmbedding(model_name=os.environ['AAC_LOCAL_EMBED_MODEL'], cache_dir=os.environ['AAC_EMBED_CACHE_DIR'])" \
    && chmod -R a+rX "$AAC_EMBED_CACHE_DIR"
ENV HF_HUB_OFFLINE=1

COPY . .

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]

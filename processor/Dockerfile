FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY processor ./processor
RUN python -m processor.main setup \
    && useradd --create-home --uid 1000 processor \
    && mkdir -p /data/private /data/gold \
    && chown -R processor:processor /data /app/data
USER processor
ENV CHAMPIONGG_DB=/data/private/champions.db CHAMPIONGG_GOLD_DIR=/data/gold
ENTRYPOINT ["python", "-m", "processor.main"]
CMD ["status"]

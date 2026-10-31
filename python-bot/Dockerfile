# Gogeta's Pet — credits: gogeta_gg
# Build:  docker build -t gogetas-pet .
# Run:    docker run --rm --env-file .env gogetas-pet
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Pehle sirf requirements — layer cache sahi kaam kare
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# SQLite runtime files yahan bante hain; non-root user ko likhne ki permission do
RUN useradd --create-home --uid 10001 bot \
    && mkdir -p /app/data \
    && chown -R bot:bot /app
USER bot

# Token .env / env-file se aata hai — image me kabhi bake nahi hota.
CMD ["python", "bot.py"]

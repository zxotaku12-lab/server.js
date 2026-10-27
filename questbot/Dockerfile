# Quest Bot — production image
#   docker build -t questbot .
#   docker run -d -p 3000:3000 -e DASHBOARD_PASSWORD=mera-pass -v questbot-data:/app/data questbot

FROM node:20-alpine

WORKDIR /app

# Dependencies pehle (cache-friendly)
COPY package*.json ./
RUN npm ci --omit=dev && npm cache clean --force

# App code
COPY . .

# Data folder (token, coins, access keys) — ise volume pe rakho
RUN mkdir -p /app/data && chown -R node:node /app
USER node

ENV NODE_ENV=production
ENV PORT=3000
EXPOSE 3000
VOLUME ["/app/data"]

CMD ["node", "src/index.js"]

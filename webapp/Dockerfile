FROM node:24-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
COPY webapp/server/package.json ./webapp/server/package.json
COPY webapp/client/package.json ./webapp/client/package.json
RUN npm ci --ignore-scripts
COPY webapp ./webapp
RUN npm run build

FROM node:24-bookworm-slim
ENV NODE_ENV=production CHAMPIONGG_GOLD_DIR=/data/gold PORT=8000
WORKDIR /app
COPY package.json package-lock.json ./
COPY webapp/server/package.json ./webapp/server/package.json
COPY webapp/client/package.json ./webapp/client/package.json
RUN npm ci --omit=dev --workspace webapp/server --ignore-scripts \
    && mkdir -p /data/gold && chown node:node /data/gold
COPY webapp/server/src ./webapp/server/src
COPY --from=build /app/webapp/client/dist ./webapp/client/dist
USER node
EXPOSE 8000
CMD ["node", "webapp/server/src/index.ts"]

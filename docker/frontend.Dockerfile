FROM docker.m.daocloud.io/node:20-alpine AS builder

WORKDIR /app

COPY frontend/package*.json ./
RUN npm config set registry "https://registry.npmmirror.com" \
    && npm ci

COPY frontend/ ./
RUN npm run build

FROM docker.m.daocloud.io/nginx:1.27-alpine

COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

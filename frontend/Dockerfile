FROM node:24-alpine AS build
WORKDIR /src

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

ARG VITE_VAULT_API_BASE_URL=/vault-api
ARG VITE_BRANCH_EXTERIOR_API_BASE_URL=/branch-api
ARG VITE_ALERT_SERVICE_BASE_URL=/alert-service
ENV VITE_VAULT_API_BASE_URL=${VITE_VAULT_API_BASE_URL} \
    VITE_BRANCH_EXTERIOR_API_BASE_URL=${VITE_BRANCH_EXTERIOR_API_BASE_URL} \
    VITE_ALERT_SERVICE_BASE_URL=${VITE_ALERT_SERVICE_BASE_URL}

COPY frontend/ ./
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.29-alpine
COPY --from=build /src/dist /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY docker/nginx-default.conf.template /etc/nginx/templates/default.conf.template

ENV NGINX_ENVSUBST_OUTPUT_DIR=/tmp/nginx/conf.d \
    NGINX_ENVSUBST_FILTER=^(VAULT_ROOM_API_KEY|ALERT_SERVICE_OPERATOR_TOKEN)$

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=4s --start-period=10s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1

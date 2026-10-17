FROM node:22-alpine AS build
WORKDIR /portal
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build
FROM nginx:1.28-alpine
COPY docker/frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /portal/dist /usr/share/nginx/html
EXPOSE 80

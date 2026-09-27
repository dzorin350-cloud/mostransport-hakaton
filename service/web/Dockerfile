FROM node:22-alpine AS build
WORKDIR /app
COPY service/web/package.json service/web/package-lock.json ./
RUN npm ci
COPY service/web/index.html ./index.html
COPY service/web/public ./public
COPY service/web/src ./src
RUN npm run build

FROM nginx:alpine
COPY service/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

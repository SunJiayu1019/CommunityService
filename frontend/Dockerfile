# ---- build 阶段：使用官方 Node 镜像 ----
FROM node:20-alpine AS build

WORKDIR /app

# npm 换淘宝源，加速依赖安装
RUN npm config set registry https://registry.npmmirror.com

COPY package*.json ./
RUN npm install

COPY . .
RUN npm run build

# ---- 部署阶段：使用官方 nginx 镜像 ----
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

FROM node:20-alpine AS ui-build
ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
WORKDIR /ui
COPY services/nginx/ui/package.json ./package.json
RUN npm install
COPY services/nginx/ui ./
RUN npm run build

FROM nginx:1.27-alpine
COPY services/nginx/nginx.conf /etc/nginx/nginx.conf
COPY --from=ui-build /ui/dist /usr/share/nginx/html
EXPOSE 80

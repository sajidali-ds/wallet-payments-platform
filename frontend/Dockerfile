# Stage 1: build the static bundle.
FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
# `npm ci` when a lockfile is committed (reproducible), `npm install` otherwise.
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY . .
RUN npm run build

# Stage 2: serve it. nginx also forwards the API paths to the gateway so the browser sees ONE origin.
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80

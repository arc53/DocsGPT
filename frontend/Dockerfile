FROM node:22-alpine AS base

WORKDIR /app

COPY package*.json ./
RUN npm ci


FROM base AS development

COPY . .

CMD ["npm", "run", "dev", "--", "--host"]


FROM base AS build

COPY . .

RUN npm run build


FROM nginx:alpine AS production

COPY --from=build /app/dist /usr/share/nginx/html

COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 5173

CMD ["nginx", "-g", "daemon off;"]

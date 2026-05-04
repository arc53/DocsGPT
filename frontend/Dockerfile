FROM node:22-alpine AS base

WORKDIR /app

COPY package*.json ./

RUN npm ci

COPY . .

FROM base AS development

# start the develpoment server of Vite
CMD ["npm", "run", "dev", "--", "--host"]


FROM base AS build

# build the application for production
RUN npm run build


FROM nginx:alpine AS production

COPY --from=build /app/dist /usr/share/nginx/html

COPY nginx.conf /etc/nginx/conf.d/default.conf

# serving on port 5173 to match the Vite development server port, making it compatible with existing setup
EXPOSE 5173

CMD ["nginx", "-g", "daemon off;"]

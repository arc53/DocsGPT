FROM node:22-alpine AS base

WORKDIR /app

COPY package*.json ./

RUN npm ci

COPY . .

FROM base AS development

# start the development server of Vite
CMD ["npm", "run", "dev", "--", "--host"]


FROM base AS build

# build the application for production
RUN npm run build


FROM nginx:alpine AS production

RUN apk add --no-cache jq

# Copy static build output of vite
COPY --from=build /app/dist /usr/share/nginx/html

# Copy nginx configuration file
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy env template 
COPY env.template.js /usr/share/nginx/html/env.template.js

# Copy entrypoint file and add execute permission
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# serving on port 5173 to match the Vite development server port, making it compatible with existing setup
EXPOSE 5173

ENTRYPOINT ["/entrypoint.sh"]

CMD ["nginx", "-g", "daemon off;"]

FROM node:22-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .

RUN npm run build

FROM node:22-alpine AS production

WORKDIR /app

COPY --from=build /app/dist ./dist

RUN npm install -g serve

EXPOSE 5173

# serving on port 5173 to match the Vite development server port, making it compatible with existing setup
CMD ["serve", "-s", "dist", "-l", "5173"]

FROM node:20.6.1-bullseye-slim


WORKDIR /app
COPY package*.json ./
RUN pnpm install
COPY . .

EXPOSE 5173

CMD [ "pnpm", "dev", "--" , "--host"]

FROM node:18-alpine3.14
UPGRADE to node:20.6.1-bullseye-slim


WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .

EXPOSE 5173

CMD [ "npm", "run", "dev", "--" , "--host"]

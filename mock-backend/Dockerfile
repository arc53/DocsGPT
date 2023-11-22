FROM node:20.6.1-bullseye-slim


WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .

EXPOSE 7091

CMD [ "npm", "run", "start"]

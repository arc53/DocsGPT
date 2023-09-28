FROM node:20.6.1-bullseye-slim


WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .

EXPOSE 5173

CMD [ "npm", "run", "dev", "--" , "--host"]

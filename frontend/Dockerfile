FROM node:20

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

COPY openssl.cnf /app/openssl.cnf

EXPOSE 5001

CMD ["npm", "run", "dev"]
FROM node:20-slim

WORKDIR /app

COPY package.json .
RUN npm install --omit=dev

COPY index.js .

ENV WA_AUTH_DIR=/data
VOLUME ["/data"]

EXPOSE 3901

CMD ["node", "index.js"]

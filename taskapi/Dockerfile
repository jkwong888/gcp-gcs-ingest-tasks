FROM node:14 as builder

WORKDIR /usr/src/app

COPY package*.json ./

RUN npm ci

COPY . .

RUN npm run build


FROM node:slim

WORKDIR /usr/src/app

COPY package*.json ./
RUN npm ci --production 

COPY --from=builder /usr/src/app/dist ./dist
EXPOSE 8000
CMD ["node", "dist/index.js"]
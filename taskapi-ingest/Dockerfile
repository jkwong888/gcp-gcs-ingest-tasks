FROM node:20 as builder

WORKDIR /usr/src/app

COPY package*.json ./

RUN npm install

COPY . .

# Build production javascript
RUN npm run build


FROM node:20-slim

WORKDIR /usr/src/app

COPY package*.json ./
RUN npm install --omit=dev 

COPY --from=builder /usr/src/app/dist ./dist
EXPOSE 8000
CMD ["node", "dist/index.js"]

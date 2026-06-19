FROM node:20 as builder

WORKDIR /usr/src/app

COPY package*.json ./

RUN npm ci

COPY . .

# Run unit tests
RUN npm test

# Build production javascript
RUN npm run build


FROM node:20-slim

WORKDIR /usr/src/app

COPY package*.json ./
RUN npm ci --production 

COPY --from=builder /usr/src/app/dist ./dist
COPY --from=builder /usr/src/app/public ./public
EXPOSE 8000
CMD ["node", "dist/index.js"]
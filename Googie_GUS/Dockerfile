FROM node:18-slim
WORKDIR /app

# Kopiuj pliki package
COPY package*.json ./

# Instaluj zależności (tylko produkcyjne)
# Używamy npm install zamiast npm ci (bardziej elastyczne dla deployment)
RUN npm install --omit=dev

# Kopiuj kod serwera
COPY server ./server

# Cloud Run wymaga nasłuchiwania na porcie z zmiennej PORT
ENV PORT=8080

# Uruchom serwer
CMD ["node", "server/index.js"]
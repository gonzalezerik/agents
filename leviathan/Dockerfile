FROM node:22-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --legacy-peer-deps
COPY . .
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

RUN apk add --no-cache python3 py3-pip supervisor && \
    pip3 install --no-cache-dir requests --break-system-packages

RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001

COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
COPY engine/leviathan_core.py ./engine/leviathan_core.py
COPY supervisord.conf /etc/supervisord.conf

RUN chown -R nextjs:nodejs /app/public

EXPOSE 3000
CMD ["supervisord", "-c", "/etc/supervisord.conf"]

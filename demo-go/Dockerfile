# Stage 1: Build Go app
FROM golang:1.23-bullseye AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN go build -o main .

# Stage 2: Final image with PostgreSQL
FROM debian:bullseye-slim
WORKDIR /app

# Install PostgreSQL and sudo
RUN apt-get update && \
    apt-get install -y postgresql postgresql-contrib sudo && \
    rm -rf /var/lib/apt/lists/*

# Copy built app and entrypoint
COPY --from=builder /app/main .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Configure PostgreSQL to allow password login from localhost
RUN echo "host all all 127.0.0.1/32 md5" >> /etc/postgresql/13/main/pg_hba.conf

EXPOSE 8080

CMD ["./entrypoint.sh"]

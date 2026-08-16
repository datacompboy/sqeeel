#!/bin/bash
set -e

# Start PostgreSQL
service postgresql start

# Wait for PostgreSQL to be ready
until pg_isready -h localhost -p 5432; do
  echo "Waiting for database..."
  sleep 2
done

# Ensure the postgres user has a password (matches main.go default)
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'postgres';"

# Run the Go app
exec /app/main

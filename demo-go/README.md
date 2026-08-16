# Demo Go Web App

A simple demo Go web application that uses a single Docker image to run both the Go server and a PostgreSQL database.

## Features

- **Database**: PostgreSQL with `categories` and `elements` tables.
- **Backend**: Golang `net/http` with `html/template`.
- **Frontend**: SSR with a search form (POST) for prefix search and category filtering.
- **Persistence**: Database is automatically initialized and seeded if empty.

## Requirements

- Docker

## How to Build and Run

1. Build the Docker image:
   ```bash
   docker build -t demo-go-app .
   ```

2. Run the Docker container:
   ```bash
   docker run -p 8080:8080 demo-go-app
   ```

3. Access the application in your browser:
   [http://localhost:8080](http://localhost:8080)

## Search Functionality

- **Name Prefix**: Enter a string to search for element names starting with that prefix.
- **Categories**: Select one or multiple categories to filter the results.
- **Combined Search**: You can use both filters simultaneously.

## Fun Functionality

The SQL code is safe. Is it?

Try it out:

```
for k in 100 1000 10000 100000 1000000; do
  echo "Size $k:"
  python -c 'print("&".join("cat=9" for k in range('$k')))' > /tmp/in && curl -d '@/tmp/in' http://localhost:8080 -o /dev/null
done
```

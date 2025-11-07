.PHONY: up down logs
up:
\tdocker compose up -d --build
down:
\tdocker compose down
logs:
\tdocker compose logs -f slicer

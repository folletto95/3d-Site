.PHONY: ps api all

ps:
\tdocker build -f api/Dockerfile.ps-build -t ps-headless:local .

api: ps
\tdocker build -f api/Dockerfile -t site-api:local .

all: api
\t@echo "Immagini pronte: ps-headless:local e site-api:local"

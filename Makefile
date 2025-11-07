# ====== Config ======
SHELL := bash
.ONESHELL:
.SHELLFLAGS := -eu -o pipefail -c

# Versioni/nomi
PS_REF            ?= version_2.9.3
PS_IMAGE          ?= ps-headless:$(PS_REF)
DOCKERFILE_PS     ?= api/Dockerfile.ps-build
BUILD_CONTEXT     ?= .

# Se vuoi forzare BuildKit
export DOCKER_BUILDKIT ?= 1

# ====== Helper ======
define need_docker
	@if ! command -v docker >/dev/null 2>&1; then \
		echo "❌ Docker non trovato nel PATH"; exit 127; \
	fi
endef

# ====== Target principali ======
.PHONY: all ps test clean ps-shell print
all: ps

## Build PrusaSlicer headless (stage ps_builder + runtime)
ps:
	$(call need_docker)
	docker build \
	  --progress=plain \
	  -f $(DOCKERFILE_PS) \
	  -t $(PS_IMAGE) \
	  --build-arg PS_REF=$(PS_REF) \
	  $(BUILD_CONTEXT)

## Test: esegue uno smoke test del binario dentro l'immagine runtime
test: test-ps

.PHONY: test-ps
test-ps:
	$(call need_docker)
	# Se l'immagine non esiste, prova a buildarla
	if ! docker image inspect $(PS_IMAGE) >/dev/null 2>&1; then \
		$(MAKE) ps; \
	fi
	# 1) Il binario risponde all'help?
	docker run --rm $(PS_IMAGE) --help >/dev/null
	echo "✅ prusa-slicer --help OK"

	# 2) Librerie dinamiche risolte? (ldd deve trovare libpng/jpeg/tiff/tbb ecc.)
	#    Nota: ldd restituisce 0 anche con 'not found', quindi controlliamo output.
	@docker run --rm $(PS_IMAGE) sh -lc 'ldd /usr/local/bin/prusa-slicer | tee /tmp/ldd.txt; ! grep -q "not found" /tmp/ldd.txt'
	echo "✅ Dipendenze dinamiche risolte"

	# 3) Versione di Debian nel runtime (informativa)
	@docker run --rm $(PS_IMAGE) sh -lc 'cat /etc/os-release || true' | sed 's/^/   /'
	echo "✅ Smoke test completato con successo"

## Shell nel runtime per debug rapido
ps-shell:
	$(call need_docker)
	docker run --rm -it --entrypoint sh $(PS_IMAGE)

## Pulizia: elimina l’immagine (non fallisce se assente)
clean:
	- docker rmi -f $(PS_IMAGE) >/dev/null 2>&1 || true

## Stampa configurazione corrente
print:
	@echo "PS_REF       = $(PS_REF)"
	@echo "PS_IMAGE     = $(PS_IMAGE)"
	@echo "DOCKERFILE   = $(DOCKERFILE_PS)"
	@echo "BUILD_CTX    = $(BUILD_CONTEXT)"

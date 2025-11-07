SHELL := /bin/bash
PS_REF ?= version_2.9.3

all: ps

ps:
	DOCKER_BUILDKIT=1 docker build -f api/Dockerfile.ps-build \
		-t ps-headless:$(PS_REF) \
		--build-arg PS_REF=$(PS_REF) .

test:
	docker run --rm ps-headless:$(PS_REF) --version

clean-images:
	docker image rm ps-headless:$(PS_REF) 2>/dev/null || true

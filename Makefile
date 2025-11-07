SHELL := /bin/bash
PS_REF ?= version_2.9.3
IMAGE_TAG ?= ps-headless:$(PS_REF)

all: ps

ps:
	DOCKER_BUILDKIT=1 docker build \
		-f api/Dockerfile.ps-build \
		-t $(IMAGE_TAG) \
		--build-arg PS_REF=$(PS_REF) .

edge:
	$(MAKE) ps PS_REF=master

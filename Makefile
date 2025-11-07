PS_REF ?= version_2.9.3
IMAGE  ?= ps-headless:$(PS_REF)

all: ps

ps:
	DOCKER_BUILDKIT=1 docker build -f api/Dockerfile.ps-build \
		-t $(IMAGE) \
		--build-arg PS_REF=$(PS_REF) .

run-version:
	docker run --rm $(IMAGE)

clean:
	-docker rmi $(IMAGE)

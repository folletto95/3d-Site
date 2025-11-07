.PHONY: all ps edge clean
PS_REF ?= version_2.9.3

all: ps

ps:
	DOCKER_BUILDKIT=1 docker build -f api/Dockerfile.ps-build -t ps-headless:$(PS_REF) --build-arg PS_REF=$(PS_REF) .

edge:
	DOCKER_BUILDKIT=1 docker build -f api/Dockerfile.ps-build -t ps-headless:edge --build-arg PS_REF=main .

clean:
	- docker image rm -f ps-headless:$(PS_REF) ps-headless:edge

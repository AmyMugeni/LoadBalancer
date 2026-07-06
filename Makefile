SHELL := /bin/bash

COMPOSE := docker compose

.PHONY: help build up down restart logs ps clean add rm test-integration

help:
	@echo "Available targets:"
	@echo "  make build              Build all images"
	@echo "  make up                 Start full stack in detached mode"
	@echo "  make down               Stop and remove containers"
	@echo "  make restart            Recreate stack"
	@echo "  make logs               Tail logs from all services"
	@echo "  make ps                 Show service status"
	@echo "  make clean              Stop stack and remove local images"
	@echo "  make add N=<count>      Add replicas via load balancer API"
	@echo "  make rm N=<count>       Remove replicas via load balancer API"
	@echo "  make test-integration   Run end-to-end endpoint checks"

build:
	$(COMPOSE) build

up:
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) down

restart: down up

logs:
	$(COMPOSE) logs -f

ps:
	$(COMPOSE) ps

clean: down
	$(COMPOSE) down --rmi local

add:
	@if [ -z "$(N)" ]; then echo "Usage: make add N=<count>"; exit 1; fi
	curl -sS -X POST http://localhost:5000/add -H "Content-Type: application/json" -d '{"n": '"$(N)"', "hostnames": []}'

rm:
	@if [ -z "$(N)" ]; then echo "Usage: make rm N=<count>"; exit 1; fi
	curl -sS -X DELETE http://localhost:5000/rm -H "Content-Type: application/json" -d '{"n": '"$(N)"', "hostnames": []}'

test-integration:
	bash ./scripts/integration_test.sh

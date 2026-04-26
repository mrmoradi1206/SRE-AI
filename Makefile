.PHONY: up down logs ps build check

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

ps:
	docker compose ps

build:
	docker compose build

check:
	python3 -m compileall shared services

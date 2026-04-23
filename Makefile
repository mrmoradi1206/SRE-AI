.PHONY: up down logs check

up:
	docker compose up -d --build

down:
	docker compose down -v

logs:
	docker compose logs -f

check:
	python3 -m compileall shared services

.PHONY: run docker-build docker-run test

run:
	python main.py

docker-build:
	docker build -t kb-sync-agent:latest .

docker-run:
	docker run --rm -e OPENAI_API_KEY=$$OPENAI_API_KEY kb-sync-agent:latest

test:
	python -m pytest tests/ -v


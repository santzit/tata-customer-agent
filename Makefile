.PHONY: install-hooks test

## Install the git pre-commit hook (run once after cloning the repo).
install-hooks:
	@cp hooks/pre-commit .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "✔ pre-commit hook installed. Tests will run before every commit."

## Run the full test suite locally (OpenAI tests skip without OPENAI_API_KEY).
test:
	POSTGRES_DSN=$${POSTGRES_DSN:-postgresql://postgres:postgres@localhost:5432/tata_agent} \
	python -m pytest tests/ --tb=short -v -s

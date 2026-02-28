.PHONY: install test lint format run

# Install dependencies
install:
	uv sync

# Run tests
test:
	uv run pytest tests/

# Run linter
lint:
	uv run ruff check src/ tests/

# Format code
format:
	uv run black src/ tests/
	uv run isort src/ tests/

# Run the application
run:
	uv run python -m src.main

# Test setup
test-setup:
	uv run python scripts/test_setup.py

# Clean
clean:
	rm -rf .pytest_cache __pycache__ */__pycache__

# Help
help:
	@echo "Available targets:"
	@echo "  install    - Install dependencies (uv sync)"
	@echo "  test       - Run tests"
	@echo "  lint       - Run linter"
	@echo "  format     - Format code"
	@echo "  run        - Run the application"
	@echo "  test-setup - Test basic setup"
	@echo "  clean      - Clean build artifacts"
	@echo "  help       - Show this help"

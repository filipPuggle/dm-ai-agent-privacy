.PHONY: help dev test smoke clean install

help:  ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install:  ## Install dependencies
	pip install -r requirements.txt

dev:  ## Run Flask development server
	@echo "Starting Flask development server..."
	@export FLASK_APP=webhook.py FLASK_ENV=development && flask run --host=0.0.0.0 --port=3000

test:  ## Run test suite
	@echo "Running tests..."
	@pytest tests/ -v --tb=short

smoke:  ## Run smoke test (simulates message flows)
	@echo "Running smoke test..."
	@python scripts/smoke_test.py

clean:  ## Clean up temporary files
	@echo "Cleaning up..."
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete
	@echo "Clean complete"

lint:  ## Run code linting (if tools installed)
	@command -v ruff >/dev/null 2>&1 && ruff check customer_capture/ tests/ || echo "ruff not installed, skipping lint"

test-sheets:  ## Test Google Sheets API integration
	@echo "Testing Google Sheets integration..."
	@python scripts/test_google_sheets.py


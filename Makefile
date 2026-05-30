.PHONY: install lint fmt test spark-test clean

VENV ?= .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev,sim]"

lint:
	$(VENV)/bin/ruff check src tests
	$(VENV)/bin/black --check src tests

fmt:
	$(VENV)/bin/ruff check --fix src tests
	$(VENV)/bin/black src tests

test:
	$(PY) -m pytest -q -m "not spark"

# Validate GPU/LLM paths on the Spark over SSH (smoke-gated).
spark-test:
	bash scripts/spark/push.sh
	bash scripts/spark/run.sh "python scripts/spark/smoke_rapids.py"
	bash scripts/spark/run.sh "python scripts/spark/smoke_ollama.py"

clean:
	rm -rf $(VENV) .pytest_cache **/__pycache__

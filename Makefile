.PHONY: install install-sim lint fmt test spark-test clean

VENV ?= .venv
PYTHON ?= python3
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

install:
	@$(PYTHON) -c 'import sys; raise SystemExit(0 if (3, 12) <= sys.version_info[:2] < (3, 14) else "Python >=3.12,<3.14 is required for the local sim dependencies")'
	@if [ -x "$(PY)" ]; then \
		venv_version=$$($(PY) -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'); \
		base_version=$$($(PYTHON) -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'); \
		if [ "$$venv_version" != "$$base_version" ]; then \
			echo "Recreating $(VENV) for Python $$base_version (was $$venv_version)"; \
			rm -rf "$(VENV)"; \
		fi; \
	fi
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev,api,data]"

install-sim: install
	@echo "Installing optional AequilibraE oracle dependency; macOS may require OpenMP-capable clang/libomp."
	$(PIP) install -e ".[sim]"

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

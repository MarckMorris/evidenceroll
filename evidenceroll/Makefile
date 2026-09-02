.PHONY: install test quality security build acceptance benchmark run clean

install:
	python -m pip install -e ".[dev]"

test:
	pytest --cov=evidenceroll --cov-report=term-missing

quality:
	ruff check .
	ruff format --check .
	mypy src

security:
	python -m pip_audit --local --skip-editable

build:
	python -m build

acceptance:
	evidenceroll simulate --scenario healthy --reset

benchmark:
	evidenceroll benchmark --output benchmark-results.json

run:
	evidenceroll serve

clean:
	rm -rf build dist htmlcov .coverage .pytest_cache .mypy_cache .ruff_cache

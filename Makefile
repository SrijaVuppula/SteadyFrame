PY ?= python
VENV ?= .venv
BIN := $(VENV)/bin
SEED ?= 1234

.PHONY: help venv install test lint synth real eval freeze report bench deploy destroy smoke web local clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

venv: ## create the virtualenv
	test -d $(VENV) || $(PY) -m venv $(VENV)
	$(BIN)/pip install -q --upgrade pip

install: venv ## install the package with dev extras (pinned)
	$(BIN)/pip install -q -r requirements.lock
	$(BIN)/pip install -q -e . --no-deps

test: ## run the test suite
	$(BIN)/python -m pytest

lint: ## ruff check + format check
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

synth: ## generate the synthetic hazard suite (deterministic, seeded)
	$(BIN)/python -m synth.generate --config synth/suite.yaml --out data/synthetic --seed $(SEED)

real: ## download the openly licensed real-world clips listed in data/SOURCES.md
	$(BIN)/python -m synth.fetch_real --out data/real

eval: ## run every evaluation script; writes eval/results/
	$(BIN)/python -m eval.detection
	$(BIN)/python -m eval.robustness
	$(BIN)/python -m eval.remediation
	$(BIN)/python -m eval.agent_vs_fixed
	$(BIN)/python -m eval.failures

freeze: ## copy eval/results into eval/results/frozen (the copy the report is rendered from) and re-render the report
	mkdir -p eval/results/frozen
	cp eval/results/*.json eval/results/*.md eval/results/*.png eval/results/frozen/
	rm -rf eval/results/frozen/failures && cp -r eval/results/failures eval/results/frozen/failures
	$(BIN)/python -m eval.report

report: ## render docs/report/REPORT.md from the frozen results
	$(BIN)/python -m eval.report

bench: ## run the analysis benchmark on this machine (see bench/README.md for the 3-config protocol)
	$(BIN)/python -m bench.run --out bench/results
	$(BIN)/python -m bench.compare bench/results/*.json --out bench/results/comparison.md

web: ## build the frontend
	cd web && npm ci && npm run build

local: ## run the API + worker locally without AWS
	docker compose up --build

deploy: ## deploy the AWS stack (needs credentials; prints the endpoint URL)
	cd infra && ../$(BIN)/cdk deploy --all --require-approval never --outputs-file cdk-outputs.json
	@$(BIN)/python -c "import json;d=json.load(open('infra/cdk-outputs.json'));[print(k,'=',v) for s in d.values() for k,v in s.items()]"

destroy: ## tear the AWS stack down
	cd infra && ../$(BIN)/cdk destroy --all --force

smoke: ## upload a synthetic clip to the deployed endpoint and check the remediated output passes
	$(BIN)/python service/smoke.py --outputs infra/cdk-outputs.json

clean:
	rm -rf .pytest_cache .ruff_cache eval/results/* bench/results/*
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

.PHONY: format lint test test-all-pythons test-e2e-fastapi test-e2e-aiohttp test-e2e-litestar test-e2e-flask test-e2e-celery test-e2e-typer docs examples-readme benchmark benchmark-artifact-dir benchmark-diwire benchmark-comparison benchmark-json benchmark-report benchmark-report-all benchmark-json-resolve benchmark-report-resolve

format:
	uv run ruff format .
	uv run ruff check --fix-only .

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy .

test:
	uv run --group docs pytest tests/ --benchmark-disable --cov=src/diwire --cov-report=term-missing

test-e2e-fastapi:
	@set +e; \
	docker compose -f tests/e2e/fastapi/docker-compose.yml up --build --abort-on-container-exit --exit-code-from tests; \
	exit_code=$$?; \
	docker compose -f tests/e2e/fastapi/docker-compose.yml down --volumes --remove-orphans; \
	exit $$exit_code

test-e2e-aiohttp:
	@set +e; \
	docker compose -f tests/e2e/aiohttp/docker-compose.yml up --build --abort-on-container-exit --exit-code-from tests; \
	exit_code=$$?; \
	docker compose -f tests/e2e/aiohttp/docker-compose.yml down --volumes --remove-orphans; \
	exit $$exit_code

test-e2e-litestar:
	@set +e; \
	docker compose -f tests/e2e/litestar/docker-compose.yml up --build --abort-on-container-exit --exit-code-from tests; \
	exit_code=$$?; \
	docker compose -f tests/e2e/litestar/docker-compose.yml down --volumes --remove-orphans; \
	exit $$exit_code

test-e2e-flask:
	@set +e; \
	docker compose -f tests/e2e/flask/docker-compose.yml up --build --abort-on-container-exit --exit-code-from tests; \
	exit_code=$$?; \
	docker compose -f tests/e2e/flask/docker-compose.yml down --volumes --remove-orphans; \
	exit $$exit_code

test-e2e-typer:
	@set +e; \
	docker compose -f tests/e2e/typer/docker-compose.yml up --build --abort-on-container-exit --exit-code-from tests; \
	exit_code=$$?; \
	docker compose -f tests/e2e/typer/docker-compose.yml down --volumes --remove-orphans; \
	exit $$exit_code

test-e2e-celery:
	@set +e; \
	docker compose -f tests/e2e/celery/docker-compose.yml up --build --abort-on-container-exit --exit-code-from tests; \
	exit_code=$$?; \
	docker compose -f tests/e2e/celery/docker-compose.yml down --volumes --remove-orphans; \
	exit $$exit_code

test-all-pythons:
	@set -e; \
	for version in 3.10 3.11 3.12 3.13 3.14 3.14t 3.15 3.15t; do \
		UV_PROJECT_ENVIRONMENT=".cache/venvs/python-$$version" \
		uv run --locked --python "$$version" --group docs \
			pytest tests/ --benchmark-disable --cov=src/diwire --cov-report=term-missing; \
	done

docs:
	rm -rf docs/_build
	uv run sphinx-build -b html docs docs/_build/html

examples-readme:
	uv run python -m tools.generate_examples_readme

# === Benchmark Commands ===

benchmark-artifact-dir:
	@test -n "$(BENCHMARK_ARTIFACT_DIR)" || ( \
		echo "BENCHMARK_ARTIFACT_DIR must name a unique directory for this run." >&2; \
		exit 2; \
	)
	@test ! -e "$(BENCHMARK_ARTIFACT_DIR)" || ( \
		echo "BENCHMARK_ARTIFACT_DIR already exists; choose a new directory." >&2; \
		exit 2; \
	)
	mkdir -p "$$(dirname "$(BENCHMARK_ARTIFACT_DIR)")"
	@mkdir "$(BENCHMARK_ARTIFACT_DIR)" || ( \
		echo "BENCHMARK_ARTIFACT_DIR already exists; choose a new directory." >&2; \
		exit 2; \
	)

benchmark:
	$(MAKE) benchmark-diwire

benchmark-diwire: benchmark-artifact-dir
	uv run pytest tests/benchmarks -k "benchmark_diwire" --benchmark-only \
		--benchmark-columns=ops --benchmark-json="$(BENCHMARK_ARTIFACT_DIR)/diwire.json" -q

benchmark-comparison: benchmark-artifact-dir
	uv run pytest tests/benchmarks/test_enter_close_scope_no_resolve.py --benchmark-only --benchmark-columns=ops --benchmark-json="$(BENCHMARK_ARTIFACT_DIR)/enter-close-scope-no-resolve.json" -q
	uv run pytest tests/benchmarks/test_enter_close_scope_resolve_once.py --benchmark-only --benchmark-columns=ops --benchmark-json="$(BENCHMARK_ARTIFACT_DIR)/enter-close-scope-resolve-once.json" -q
	uv run pytest tests/benchmarks/test_enter_close_scope_resolve_100_instance.py --benchmark-only --benchmark-columns=ops --benchmark-json="$(BENCHMARK_ARTIFACT_DIR)/enter-close-scope-resolve-100-instance.json" -q
	uv run pytest tests/benchmarks/test_enter_close_scope_resolve_scoped_100.py --benchmark-only --benchmark-columns=ops --benchmark-json="$(BENCHMARK_ARTIFACT_DIR)/enter-close-scope-resolve-scoped-100.json" -q
	uv run pytest tests/benchmarks/test_enter_close_scope_resolve_generator_request_try_finally.py --benchmark-only --benchmark-columns=ops --benchmark-json="$(BENCHMARK_ARTIFACT_DIR)/enter-close-scope-resolve-generator-request.json" -q
	uv run pytest tests/benchmarks/test_enter_close_scope_resolve_open_generic_scoped.py --benchmark-only --benchmark-columns=ops --benchmark-json="$(BENCHMARK_ARTIFACT_DIR)/enter-close-scope-resolve-open-generic-scoped.json" -q
	uv run pytest tests/benchmarks/test_resolve_deep_transient_chain.py --benchmark-only --benchmark-columns=ops --benchmark-json="$(BENCHMARK_ARTIFACT_DIR)/resolve-deep-transient-chain.json" -q
	uv run pytest tests/benchmarks/test_resolve_wide_transient_graph.py --benchmark-only --benchmark-columns=ops --benchmark-json="$(BENCHMARK_ARTIFACT_DIR)/resolve-wide-transient-graph.json" -q
	uv run pytest tests/benchmarks/test_resolve_singleton.py --benchmark-only --benchmark-columns=ops --benchmark-json="$(BENCHMARK_ARTIFACT_DIR)/resolve-singleton.json" -q
	uv run pytest tests/benchmarks/test_resolve_transient.py --benchmark-only --benchmark-columns=ops --benchmark-json="$(BENCHMARK_ARTIFACT_DIR)/resolve-transient.json" -q
	uv run pytest tests/benchmarks/test_resolve_open_generic_transient.py --benchmark-only --benchmark-columns=ops --benchmark-json="$(BENCHMARK_ARTIFACT_DIR)/resolve-open-generic-transient.json" -q
	uv run pytest tests/benchmarks/test_resolve_scoped.py --benchmark-only --benchmark-columns=ops --benchmark-json="$(BENCHMARK_ARTIFACT_DIR)/resolve-scoped.json" -q
	uv run pytest tests/benchmarks/test_resolve_scoped_with_registered_open_closed_generics.py --benchmark-only --benchmark-columns=ops --benchmark-json="$(BENCHMARK_ARTIFACT_DIR)/resolve-scoped-open-closed-generics.json" -q
	uv run pytest tests/benchmarks/test_resolve_scoped_with_registered_open_closed_generics_pair_same.py --benchmark-only --benchmark-columns=ops --benchmark-json="$(BENCHMARK_ARTIFACT_DIR)/resolve-scoped-open-closed-generics-pair-same.json" -q
	uv run pytest tests/benchmarks/test_resolve_scoped_with_registered_open_closed_generics_pair_alternating.py --benchmark-only --benchmark-columns=ops --benchmark-json="$(BENCHMARK_ARTIFACT_DIR)/resolve-scoped-open-closed-generics-pair-alternating.json" -q
	uv run pytest tests/benchmarks/test_resolve_mixed_lifetimes.py --benchmark-only --benchmark-columns=ops --benchmark-json="$(BENCHMARK_ARTIFACT_DIR)/resolve-mixed-lifetimes.json" -q
	uv run pytest tests/benchmarks/test_resolve_generated_scoped_grid.py --benchmark-only --benchmark-columns=ops --benchmark-json="$(BENCHMARK_ARTIFACT_DIR)/resolve-generated-scoped-grid.json" -q

benchmark-json: benchmark-artifact-dir
	uv run pytest tests/benchmarks --benchmark-only -q \
		--benchmark-json="$(BENCHMARK_ARTIFACT_DIR)/all.json"

benchmark-report: benchmark-json
	uv run python -m tools.benchmark_reporting \
		--input "$(BENCHMARK_ARTIFACT_DIR)/all.json" \
		--markdown "$(BENCHMARK_ARTIFACT_DIR)/benchmark-table.md" \
		--json "$(BENCHMARK_ARTIFACT_DIR)/benchmark-table.json" \
		--comment "$(BENCHMARK_ARTIFACT_DIR)/pr-comment.md" \
		--libraries diwire,rodi,dishka,wireup

benchmark-report-all: benchmark-json
	uv run python -m tools.benchmark_reporting \
		--input "$(BENCHMARK_ARTIFACT_DIR)/all.json" \
		--markdown "$(BENCHMARK_ARTIFACT_DIR)/benchmark-table-all.md" \
		--json "$(BENCHMARK_ARTIFACT_DIR)/benchmark-table-all.json" \
		--comment "$(BENCHMARK_ARTIFACT_DIR)/pr-comment-all.md" \
		--libraries diwire,rodi,dishka,wireup

benchmark-json-resolve: benchmark-artifact-dir
	uv run pytest \
		tests/benchmarks/test_resolve_transient.py \
		tests/benchmarks/test_resolve_open_generic_transient.py \
		tests/benchmarks/test_resolve_singleton.py \
		tests/benchmarks/test_resolve_deep_transient_chain.py \
		tests/benchmarks/test_resolve_wide_transient_graph.py \
		tests/benchmarks/test_resolve_scoped_with_registered_open_closed_generics.py \
		tests/benchmarks/test_resolve_scoped_with_registered_open_closed_generics_pair_same.py \
		tests/benchmarks/test_resolve_scoped_with_registered_open_closed_generics_pair_alternating.py \
		tests/benchmarks/test_resolve_generated_scoped_grid.py \
		--benchmark-only -q --benchmark-json="$(BENCHMARK_ARTIFACT_DIR)/resolve.json"

benchmark-report-resolve: benchmark-json-resolve
	uv run python -m tools.benchmark_reporting \
		--input "$(BENCHMARK_ARTIFACT_DIR)/resolve.json" \
		--markdown "$(BENCHMARK_ARTIFACT_DIR)/benchmark-table-resolve.md" \
		--json "$(BENCHMARK_ARTIFACT_DIR)/benchmark-table-resolve.json" \
		--comment "$(BENCHMARK_ARTIFACT_DIR)/pr-comment-resolve.md" \
		--libraries diwire,rodi,dishka,wireup

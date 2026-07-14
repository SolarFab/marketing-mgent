# Wrappers so demo commands are one word — no venv or cwd juggling on stage.
#
#   make test     — run the full pytest suite (104 tests, ~2min)
#   make fast     — the fast subset (no LLM, no DB) — ~5s
#   make eval     — regenerate the multi-framework eval report
#   make dev      — start backend (:8765) + frontend (:3001) together
#   make backend  — just backend
#   make frontend — just frontend

PYTHON := /Users/solarlord/Projects/.venv/bin/python
PYTEST := /Users/solarlord/Projects/.venv/bin/pytest
UVICORN := /Users/solarlord/Projects/.venv/bin/uvicorn

.PHONY: test fast eval dev backend frontend clean-carousels clean-uploads

test:
	$(PYTEST) -q

fast:
	$(PYTEST) tests/test_crawl.py tests/test_sources_normalize.py tests/test_evaluate.py tests/test_smoke.py -q

eval:
	$(PYTHON) -m backend.eval.run_eval --slug live-demo --company-id demo

backend:
	$(UVICORN) backend.app:app --host 127.0.0.1 --port 8765 --reload

frontend:
	cd frontend && npm run dev

dev:
	@echo "Start backend in one terminal:  make backend"
	@echo "Start frontend in another:      make frontend"
	@echo "Open http://localhost:3001"

# Housekeeping between demo runs
clean-carousels:
	rm -rf data/carousels/*

clean-uploads:
	rm -rf data/user-uploads/*

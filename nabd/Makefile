.PHONY: setup doctor seed seed-full api web dev demo test
setup:            ## install backend and frontend dependencies
	cd backend && uv sync
	cd frontend && npm install
doctor:           ## check Python, database, Codex sign-in and keys
	cd backend && uv run nabd doctor
seed:             ## open data plus a first run of every model (about 3 minutes)
	cd backend && uv run nabd seed
seed-full:        ## seed plus 30 days of news and the news history since 2019 (~1 GB, 30+ minutes)
	cd backend && uv run nabd seed --full
api:              ## FastAPI on 127.0.0.1:8000
	cd backend && uv run nabd serve --port 8000
web:              ## Vite on localhost:5173 (proxies /api to the API)
	cd frontend && npm run dev
dev:              ## API and web app together
	./scripts/dev.sh
demo: setup doctor seed dev   ## from a fresh clone: install, check, seed, run
test:
	cd backend && uv run pytest -q && uv run ruff check app tests
	cd frontend && npm run typecheck

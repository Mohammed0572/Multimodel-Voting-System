.PHONY: help install install-node install-python install-tesseract compile ganache migrate backend frontend dev test test-frontend test-backend test-contracts build lint clean docker-up docker-down demo

# Executable configurations
PNPM ?= pnpm
PYTHON ?= python
GANACHE ?= npx ganache
TRUFFLE ?= npx truffle
TESSERACT ?= tesseract

# Virtual environment python detection
VENV_PY_WIN = server/face-recognition/.venv/Scripts/python.exe
VENV_PY_UNIX = server/face-recognition/.venv/bin/python
ifneq ($(wildcard $(VENV_PY_WIN)),)
	BACKEND_PY := $(VENV_PY_WIN)
else ifneq ($(wildcard $(VENV_PY_UNIX)),)
	BACKEND_PY := $(VENV_PY_UNIX)
else
	BACKEND_PY := $(PYTHON)
endif

help:
	@echo "========================================================"
	@echo "           Multimodal Voting System Makefile            "
	@echo "========================================================"
	@echo "Available commands:"
	@echo "  make install           - Install all dependencies (Node, Python & Tesseract OCR)"
	@echo "  make install-node      - Install Node.js dependencies via pnpm"
	@echo "  make install-python    - Install Python face-recognition dependencies"
	@echo "  make install-tesseract - Check and install Tesseract OCR dependency"
	@echo "  make compile           - Compile Solidity smart contracts"
	@echo "  make ganache           - Start local Ganache blockchain on port 7545"
	@echo "  make migrate           - Deploy smart contracts to local Ganache"
	@echo "  make backend           - Start FastAPI face recognition backend"
	@echo "  make frontend          - Start Vite React frontend"
	@echo "  make dev               - Check dependencies & start Vite React frontend"
	@echo "  make build             - Build the frontend for production"
	@echo "  make lint              - Run linter (ESLint)"
	@echo "  make test              - Run all tests (frontend, backend, contracts)"
	@echo "  make test-frontend     - Run React/Vitest tests"
	@echo "  make test-backend      - Run Python/Pytest backend tests"
	@echo "  make test-contracts    - Run Truffle smart contract tests"
	@echo "  make demo              - Launch full demo (Ganache, migrations, backend, frontend)"
	@echo "  make docker-up         - Start full containerized stack via Docker Compose"
	@echo "  make docker-down       - Stop Docker Compose stack"
	@echo "  make clean             - Remove build and cache artifacts"
	@echo "========================================================"

install: install-node install-python install-tesseract

install-node:
	@echo "[*] Installing Node.js dependencies..."
	$(PNPM) install

install-python:
	@echo "[*] Installing Python backend dependencies..."
	$(BACKEND_PY) -m pip install -r server/face-recognition/requirements.txt

install-tesseract:
	@echo "[*] Checking Tesseract OCR dependency..."
	@node scripts/install-tesseract.mjs

dev: install-tesseract frontend

compile:
	@echo "[*] Compiling Solidity smart contracts..."
	$(TRUFFLE) compile

ganache:
	@echo "[*] Starting local Ganache blockchain on port 7545 (networkId 1337)..."
	$(GANACHE) --port 7545 --deterministic --networkId 1337

migrate:
	@echo "[*] Deploying smart contracts to Ganache..."
	$(TRUFFLE) migrate --reset --config server/blockchain/truffle-config.js

backend:
	@echo "[*] Starting FastAPI face recognition backend on http://127.0.0.1:8000..."
	$(BACKEND_PY) -m uvicorn --app-dir server/face-recognition main:app --host 127.0.0.1 --port 8000 --reload

frontend:
	@echo "[*] Starting Vite React frontend..."
	$(PNPM) run dev

build:
	@echo "[*] Building frontend for production..."
	$(PNPM) run build

lint:
	@echo "[*] Running linter..."
	$(PNPM) run lint

test: test-frontend test-backend test-contracts

test-frontend:
	@echo "[*] Running frontend vitest suite..."
	$(PNPM) run test

test-backend:
	@echo "[*] Running Python backend tests..."
	pytest server/face-recognition

test-contracts:
	@echo "[*] Running smart contract tests..."
	$(PNPM) run test:blockchain

docker-up:
	@echo "[*] Starting Docker Compose stack..."
	docker compose -f server/docker-compose.yml up -d

docker-down:
	@echo "[*] Stopping Docker Compose stack..."
	docker compose -f server/docker-compose.yml down

demo: install-tesseract
	@node scripts/start-demo.mjs

clean:
	@echo "[*] Cleaning build artifacts and cache..."
	-rm -rf dist build src/contracts/*.json .pytest_cache

# Multimodal Blockchain Voting System

An academic voting prototype with a React web app, a FastAPI face-authentication service, a SQLite voter registry, and a Solidity contract for election state and vote tallies.

> **Scope:** This is a local/testnet prototype, not a production election system. Face matching, a one-use liveness challenge, head movement, and blink checks are limited authentication signals; they are not certified anti-spoofing and cannot guarantee rejection of a well-made replay. The voter registry, eligibility review, credential issuance, and blockchain relayer are trusted centralized services. The public contract records candidate totals and one-time credential hashes; it does not provide cryptographic ballot secrecy or coercion resistance.

## Project layout

```text
src/                         React and TypeScript frontend
server/face-recognition/     FastAPI API, face utilities, SQLite setup, Python tests
server/blockchain/           Solidity contract, Truffle config, migrations, tests
scripts/start-demo.mjs       Starts local Ganache, API, and Vite together
Makefile                     Common setup, run, lint, build, and test commands
```

## Prerequisites

- Node.js supported by Vite 8 (Node 20.19+ or 22.12+ recommended)
- pnpm
- Python 3.10, 3.11, or 3.12 for the face-recognition dependencies
- A webcam for face enrollment and login
- GNU Make for the `make` commands

On Windows, install GNU Make (for example, with Chocolatey or MSYS2) and the Python launcher (`py`). The demo uses the bundled Ganache package; you do not need to start a separate Ganache app.

## Run the local demo

From the repository root:

```bash
make demo
```

The Make target installs the Node and Python dependencies, starts Ganache on port `7545`, deploys the contract, starts FastAPI on port `8000`, then starts Vite on port `8080`. The application uses local chain ID `1337` in demo mode. Add `http://127.0.0.1:7545` / chain ID `1337` to MetaMask if you want to connect a wallet.

Open <http://localhost:8080>. Keep the terminal open while using the app; press **Ctrl+C** there to stop the services. To restart, run `make demo` again after the previous demo has stopped. The launcher exits with an explanation if one of its required ports is already in use.

The demo administrator is `admin_user` by default. If `ADMIN_PASSWORD` is empty in the root `.env`, the launcher generates a temporary password and prints it in the demo terminal each time it starts. Do not use the deterministic Ganache accounts, development relayer key, or temporary demo credentials with real funds or real elections.

## Environment files

The checked-in examples contain variable names and safe local defaults only. Copy them before configuring a manual or deployed setup:

```powershell
Copy-Item .env.example .env
Copy-Item server/face-recognition/.env.example server/face-recognition/.env
```

On macOS/Linux, use `cp` in place of `Copy-Item`. Keep the resulting `.env` files private; they are ignored by Git. The demo reads the root `.env` for its admin credentials and deployment configuration. A manually started FastAPI process reads `server/face-recognition/.env` when launched from that directory.

| Variable | Used by | Notes |
| --- | --- | --- |
| `NODE_SECRET_KEY` | Express server | Set a unique random value for a deployed Express server. |
| `SECRET_KEY` | FastAPI | Set a unique random value; changing it invalidates existing login tokens. |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | Demo / FastAPI | The demo generates a temporary password when the root value is empty. Use a non-default username and strong password outside the demo. |
| `VITE_API_BASE_URL` | Vite frontend | Defaults to the local FastAPI service. Vite variables are public in the browser bundle. |
| `VITE_CONTRACT_ADDRESS`, `VITE_NETWORK_ID` | Vite frontend | The demo supplies the local contract address and chain ID automatically. |
| `MNEMONIC`, `SEPOLIA_RPC_URL`, `RELAYER_ADDRESS` | Truffle | Optional Sepolia deployment configuration. Never commit a mnemonic or private key. |
| `BLOCKCHAIN_*` | FastAPI relayer | Server-only RPC and relayer configuration. Never use a `VITE_` prefix for secrets. |
| `FACE_DB_PATH`, `REDIS_URL`, `FRONTEND_ORIGINS` | FastAPI | Database location, rate-limit store, and allowed browser origins. Redis is optional for local use; the API falls back to in-memory rate limiting. |

Generate a backend secret with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

The root `.env.example` covers the local demo and optional Truffle/Vite settings. The backend-specific example documents FastAPI settings and defaults. The demo launcher injects its local contract address and development relayer configuration when it starts the backend.

## Manual development

Install frontend dependencies:

```bash
pnpm install
```

Create a Python virtual environment and install the face API dependencies. On Windows:

```powershell
py -3.12 -m venv server/face-recognition/.venv
server/face-recognition/.venv/Scripts/python.exe -m pip install -r server/face-recognition/requirements.txt
server/face-recognition/.venv/Scripts/python.exe -m pip install --no-deps "face-recognition>=1.3.0"
```

On macOS/Linux, replace `py -3.12` with `python3.12` and use `.venv/bin/python`. `dlib-bin` supplies the native dlib module; installing the `face-recognition` wrapper with `--no-deps` avoids an unnecessary attempt to build dlib from source. OCR is optional and can be installed with `pip install -r server/face-recognition/requirements-ocr.txt`.

For a complete local voting flow, use `make demo`. For frontend-only work, run `pnpm run dev`. For manual FastAPI startup, set up its `.env` as above and run from the API directory:

```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

The health endpoint is <http://127.0.0.1:8000/health>.

## Tests and quality checks

Run the full suite:

```bash
make test
```

Or run checks individually:

```bash
pnpm run lint
pnpm run test
pnpm run build
python -m pytest server/face-recognition -q
pnpm run test:blockchain
```

The build compiles the Solidity contracts before TypeScript checking and the Vite production bundle. Python tests use mocks for face detection and temporary SQLite databases; no webcam is needed. Contract tests start an in-process Ganache provider.

## How a vote is recorded

1. A voter enrolls a face and submits their ID details. An administrator reviews eligibility.
2. Login requires a fresh, voter-bound, one-use server challenge. The API checks a sequence of camera frames for side-to-side head movement, a blink, and a matching face before granting a session.
3. The API issues a short-lived, one-time voting credential when the voter is eligible.
4. The API relayer submits the selected candidate and a hash of that credential to the contract.
5. The contract accepts votes only while the election is active, increments the selected candidate's public count, and rejects reuse of a credential hash.
6. An administrator can end the election; the dashboard displays the final candidate totals and winner.

The blockchain provides tamper-evident election state and vote totals after confirmation. It does not validate a voter's real-world identity or independently decide eligibility; those remain API and administrator responsibilities.

## License

MIT. See [LICENSE](LICENSE).

# Deployment notes

Use [README](../README.md) as the setup reference and review the [security report](security/hardening-report-2026-11-01.md) before exposing this academic prototype publicly.

React lives in `src`, built assets in `dist`, the optional Express static server is root `index.ts`, and FastAPI is `server/face-recognition/main.py`. There is no `Database_API` directory or `server/src/app.ts` API.

1. Install root pnpm dependencies and compile/deploy the contract to a private local/testnet RPC. Routine restarts must not reset an election.
2. Configure environment files from the examples. Build Vite with the actual public API URL, contract address and network ID. Keep secrets server-side.
3. Create a Python 3.12.7 virtual environment and follow the README installation steps, including `face-recognition --no-deps` with `dlib-bin`.
4. From the root, run `python -m uvicorn main:app --app-dir server/face-recognition --host 127.0.0.1 --port 8000`. Use `pnpm run serve` for the built frontend or serve `dist` with SPA fallback.
5. Terminate HTTPS at a trusted proxy, set `COOKIE_SECURE=true`, configure exact browser origins and preserve API paths. Keep FastAPI, Redis and RPC off the public internet. An exposed unlocked Ganache node gives callers control of development accounts.
6. Use `REQUIRE_REDIS=true` for shared rate limits. All API workers must share one local SQLite file and one exclusive relayer key.
7. Preserve the database, demo chain where applicable, and signing secrets across restarts. Use SQLite's backup API; do not clear pending ballots to work around failures.

Compose defines frontend/API/Redis services and requires an external configured RPC and deployed contract. Build-time Vite settings must match. Backend builds now copy OCR requirements before installation and exclude local secrets/biometrics. Docker execution was not validated here.

Use a restricted service account and your existing service manager. The included Nginx files are templates to review for your hostname, TLS paths, API forwarding and camera access, not proof of a secure live deployment.

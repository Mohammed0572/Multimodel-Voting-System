# EC2 deployment notes

Follow [the current deployment guide](DEPLOYMENT.md). Previous instructions referred to nonexistent `Database_API` and `server/src/app.ts` paths.

Expose only a reviewed HTTPS frontend/proxy and restricted management access. Keep Ganache/RPC, Redis and FastAPI private. Use a restricted service account, encrypted persistent storage/backups, stable server secrets and a service manager. Review `server/deploy/voting-system.nginx` for your hostname, TLS paths, API forwarding and camera permissions.

No EC2 deployment was performed or certified by this repository audit.

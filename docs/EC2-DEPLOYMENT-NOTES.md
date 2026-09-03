# AWS EC2 Migration & Deployment Notes

This document outlines the steps and architecture required to migrate the entire Prajatantra e-Voting Platform (Frontend, Node.js API, and FastAPI Face Auth) to a single AWS EC2 instance.

## 1. Recommended EC2 Setup
- **Instance Type**: `t3.medium` or higher (FastAPI and React build processes require adequate RAM).
- **OS**: Ubuntu 22.04 LTS or 24.04 LTS.
- **Security Group (Inbound Rules)**:
  - Port 22 (SSH)
  - Port 80 (HTTP)
  - Port 443 (HTTPS) - **Crucial**: The webcam API requires a secure context (HTTPS) to function.
  - Port 8545 (if exposing Ganache externally, though keeping it internal/localhost is more secure).

## 2. Server Prerequisites

Connect to your EC2 instance and install the required dependencies:

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Node.js (via NVM)
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
source ~/.bashrc
nvm install 20
nvm use 20

# Install Python 3.12 and venv
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt update
sudo apt install python3.12 python3.12-venv -y

# Install Nginx
sudo apt install nginx -y

# Install PM2 (Process Manager for Node & Python)
npm install -g pm2 pnpm
```

## 3. Deployment Steps

### A. Frontend (React/Vite)
1. Build the production application:
   ```bash
   pnpm install
   pnpm run build
   ```
2. The compiled static files will be in the `dist/` directory. Nginx will serve these files directly.

### B. Node.js Backend (`server/`)
1. Navigate to the server folder and install dependencies.
2. Start the Express server using PM2:
   ```bash
   cd server
   pnpm install
   pm2 start src/app.ts --interpreter ./node_modules/.bin/ts-node --name "node-api"
   ```

### C. FastAPI Backend (`Database_API/`)
1. Setup Python environment:
   ```bash
   cd Database_API
   python3.12 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
2. Start FastAPI using PM2 and Uvicorn:
   ```bash
   pm2 start "venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000" --name "fastapi-auth"
   ```

### D. Save PM2 State
Ensure services restart automatically if the EC2 instance reboots:
```bash
pm2 save
pm2 startup
```

## 4. Nginx Reverse Proxy Configuration

You will need Nginx to route traffic to the correct internal services. Copy the provided `voting-system.nginx` file to your server's Nginx configuration directory:

```bash
sudo cp voting-system.nginx /etc/nginx/sites-available/voting-system
```

Enable the site and restart Nginx:
```bash
sudo ln -s /etc/nginx/sites-available/voting-system /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

## 5. SSL / HTTPS Setup (Required for Camera Access)

Modern browsers block webcam access (required for voter authentication) on `http://`. You must secure the EC2 instance using Let's Encrypt:

```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d your-domain.com
```

## 6. Environment Variables
You must create `.env` files on the server exactly like your local setup. Ensure `settings.py` or `.env` has the correct remote database credentials and secure random keys. Do not commit these production `.env` files to Git.

import { spawn, spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import dotenv from "dotenv";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");
dotenv.config({ path: path.join(rootDir, ".env") });

// ANSI Color codes
const colors = {
  reset: "\x1b[0m",
  bright: "\x1b[1m",
  cyan: "\x1b[36m",
  green: "\x1b[32m",
  yellow: "\x1b[33m",
  blue: "\x1b[34m",
  magenta: "\x1b[35m",
  red: "\x1b[31m",
};

const prefix = {
  ganache: `${colors.yellow}[Ganache]${colors.reset} `,
  migrate: `${colors.cyan}[Migrate]${colors.reset} `,
  backend: `${colors.magenta}[Backend]${colors.reset} `,
  frontend: `${colors.green}[Frontend]${colors.reset} `,
  system: `${colors.bright}${colors.blue}[System]${colors.reset} `,
};

const activeProcesses = [];

function log(systemPrefix, message) {
  console.log(`${systemPrefix}${message}`);
}

function pipeOutput(child, logPrefix) {
  child.stdout?.on("data", (data) => {
    const lines = data.toString().trimEnd().split("\n");
    for (const line of lines) {
      if (line.trim()) console.log(`${logPrefix}${line}`);
    }
  });

  child.stderr?.on("data", (data) => {
    const lines = data.toString().trimEnd().split("\n");
    for (const line of lines) {
      if (line.trim()) console.error(`${logPrefix}${line}`);
    }
  });
}

function findPython() {
  const venvWin = path.join(
    rootDir,
    "server",
    "face-recognition",
    ".venv",
    "Scripts",
    "python.exe",
  );
  const venvUnix = path.join(
    rootDir,
    "server",
    "face-recognition",
    ".venv",
    "bin",
    "python",
  );

  if (fs.existsSync(venvWin)) return { command: venvWin, args: [] };
  if (fs.existsSync(venvUnix)) return { command: venvUnix, args: [] };
  if (process.env.PYTHON?.trim()) {
    return { command: process.env.PYTHON.trim(), args: [] };
  }

  if (process.platform === "win32") {
    for (const version of ["3.12", "3.11", "3.10"]) {
      const result = spawnSync("py", [`-${version}`, "--version"], {
        encoding: "utf8",
        windowsHide: true,
      });
      if (result.status === 0) {
        return { command: "py", args: [`-${version}`] };
      }
    }
    throw new Error(
      "Python 3.12, 3.11, or 3.10 is required for the face-recognition backend. Install one or set up server/face-recognition/.venv.",
    );
  }

  for (const command of ["python3.12", "python3.11", "python3.10"]) {
    const result = spawnSync(command, ["--version"], {
      encoding: "utf8",
      windowsHide: true,
    });
    if (result.status === 0) return { command, args: [] };
  }
  throw new Error(
    "Python 3.12, 3.11, or 3.10 is required for the face-recognition backend. Install one or set up server/face-recognition/.venv.",
  );
}

function resolveCli(packageName, relativeCliPath) {
  const directPath = path.join(
    rootDir,
    "node_modules",
    packageName,
    relativeCliPath,
  );
  if (fs.existsSync(directPath)) {
    return { command: process.execPath, args: [directPath], isCmd: false };
  }
  const isWin = process.platform === "win32";
  const binFile = isWin ? `${packageName}.cmd` : packageName;
  const localBin = path.join(rootDir, "node_modules", ".bin", binFile);
  if (fs.existsSync(localBin)) {
    return { command: localBin, args: [], isCmd: isWin };
  }
  return { command: "npx", args: [packageName], isCmd: isWin };
}

function spawnService(command, args, options = {}) {
  const isCmd =
    options.isCmd ??
    (process.platform === "win32" &&
      (command.endsWith(".cmd") || command.endsWith(".bat")));
  return spawn(command, args, {
    cwd: rootDir,
    shell: isCmd,
    stdio: "pipe",
    ...options,
  });
}

function waitForPort(port, host = "127.0.0.1", timeoutMs = 45000) {
  const startTime = Date.now();
  let lastLoggedSec = 0;

  return new Promise((resolve, reject) => {
    const check = () => {
      const socket = new net.Socket();
      socket.setTimeout(800);

      socket.once("connect", () => {
        socket.destroy();
        resolve();
      });

      const retry = () => {
        socket.destroy();
        const elapsed = Date.now() - startTime;
        if (elapsed > timeoutMs) {
          reject(
            new Error(
              `Timeout waiting for port ${port} after ${Math.round(timeoutMs / 1000)}s. Please check that Ganache is able to start without port conflicts.`,
            ),
          );
        } else {
          const elapsedSec = Math.floor(elapsed / 1000);
          if (
            elapsedSec >= 4 &&
            elapsedSec !== lastLoggedSec &&
            elapsedSec % 4 === 0
          ) {
            lastLoggedSec = elapsedSec;
            log(
              prefix.system,
              `Still waiting for port ${port} (${elapsedSec}s elapsed)...`,
            );
          }
          setTimeout(check, 300);
        }
      };

      socket.once("error", retry);
      socket.once("timeout", retry);

      socket.connect(port, host);
    };

    check();
  });
}

function checkPortAvailable(port, host) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.listen(port, host, () => server.close(() => resolve(true)));
  });
}

async function assertRequiredPortsAvailable() {
  const required = [
    { name: "Ganache", port: 7545, hosts: ["127.0.0.1"] },
    { name: "FastAPI", port: 8000, hosts: ["127.0.0.1"] },
    { name: "Vite", port: 8080, hosts: ["127.0.0.1", "::1"] },
  ];
  const busy = [];

  for (const service of required) {
    for (const host of service.hosts) {
      if (!(await checkPortAvailable(service.port, host))) {
        busy.push(`${service.name} port ${service.port} (${host})`);
      }
    }
  }

  if (busy.length > 0) {
    throw new Error(
      `Cannot start the demo because these required ports are already in use: ${busy.join(", ")}. Stop the existing project instance (Ctrl+C in its terminal) or close the process using those ports, then run make demo again.`,
    );
  }
}

function waitForHttp(url, serviceProcess, timeoutMs = 45000) {
  const startTime = Date.now();
  let lastLoggedSec = 0;

  return new Promise((resolve, reject) => {
    const check = async () => {
      try {
        const response = await fetch(url);
        if (response.ok) {
          resolve();
          return;
        }
      } catch (_) {
        // The service may still be completing application startup.
      }

      if (serviceProcess.exitCode !== null || serviceProcess.signalCode !== null) {
        reject(
          new Error(
            `Backend exited before ${url} became healthy (exit code ${serviceProcess.exitCode ?? "unknown"}). See the backend output above.`,
          ),
        );
        return;
      }

      const elapsed = Date.now() - startTime;
      if (elapsed > timeoutMs) {
        reject(
          new Error(
            `Timeout waiting for ${url} after ${Math.round(timeoutMs / 1000)}s.`,
          ),
        );
        return;
      }

      const elapsedSec = Math.floor(elapsed / 1000);
      if (
        elapsedSec >= 4 &&
        elapsedSec !== lastLoggedSec &&
        elapsedSec % 4 === 0
      ) {
        lastLoggedSec = elapsedSec;
        log(
          prefix.system,
          `Still waiting for ${url} (${elapsedSec}s elapsed)...`,
        );
      }
      setTimeout(check, 300);
    };

    void check();
  });
}

function runCommand(
  command,
  args,
  cwd = rootDir,
  logPrefix = prefix.system,
  isCmd = false,
) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd,
      shell: isCmd,
      stdio: "pipe",
    });

    pipeOutput(child, logPrefix);

    child.on("close", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`Command failed with exit code ${code}`));
    });
  });
}

function cleanup() {
  log(prefix.system, "Shutting down all services...");
  for (const proc of activeProcesses) {
    try {
      if (process.platform === "win32" && proc.pid) {
        spawn("taskkill", ["/pid", proc.pid.toString(), "/f", "/t"], {
          stdio: "ignore",
        });
      } else {
        proc.kill("SIGINT");
      }
    } catch (_) {
      // Ignore errors during shutdown
    }
  }
}

process.on("SIGINT", () => {
  cleanup();
  process.exit(0);
});

process.on("SIGTERM", () => {
  cleanup();
  process.exit(0);
});

async function main() {
  console.log(
    `\n${colors.bright}${colors.cyan}======================================================${colors.reset}`,
  );
  console.log(
    `${colors.bright}${colors.cyan}   Multimodal Voting System - Starting All Services   ${colors.reset}`,
  );
  console.log(
    `${colors.bright}${colors.cyan}======================================================${colors.reset}\n`,
  );

  // Fail before starting Ganache or deploying contracts if a previous demo
  // instance (or another app) still owns one of the required ports.
  await assertRequiredPortsAvailable();

  // 1. Start Ganache
  log(
    prefix.system,
    "Starting Ganache blockchain on port 7545 (networkId 1337)...",
  );
  const ganacheCli = resolveCli("ganache", path.join("dist", "node", "cli.js"));
  const ganacheDataDir = path.join(rootDir, ".ganache", "demo-chain");
  const ganacheProc = spawnService(
    ganacheCli.command,
    [
      ...ganacheCli.args,
      "--port",
      "7545",
      "--deterministic",
      "--networkId",
      "1337",
      // Keep the local chain's block history when make demo is restarted.
      // MetaMask may retain references to old block numbers for this network;
      // resetting Ganache to genesis under the same chain ID makes those
      // eth_getCode/eth_call requests fail with "header not found".
      "--database.dbPath",
      ganacheDataDir,
      "--logging.verbose=false",
    ],
    { isCmd: ganacheCli.isCmd },
  );
  activeProcesses.push(ganacheProc);
  pipeOutput(ganacheProc, prefix.ganache);

  log(prefix.system, "Waiting for Ganache blockchain to be ready...");
  await waitForPort(7545);
  log(prefix.system, "Ganache is ready!");

  // 2. Run Truffle Migrate
  log(prefix.system, "Deploying smart contracts to Ganache...");
  try {
    const truffleCli = resolveCli(
      "truffle",
      path.join("build", "cli.bundled.js"),
    );
    await runCommand(
      truffleCli.command,
      [
        ...truffleCli.args,
        "migrate",
        "--reset",
        "--config",
        "server/blockchain/truffle-config.js",
      ],
      rootDir,
      prefix.migrate,
      truffleCli.isCmd,
    );
    log(prefix.system, "Smart contracts successfully deployed!");
  } catch (err) {
    log(
      prefix.system,
      `${colors.red}Contract deployment failed: ${err.message}${colors.reset}`,
    );
    cleanup();
    process.exit(1);
  }

  const votingArtifact = JSON.parse(
    fs.readFileSync(
      path.join(rootDir, "src", "contracts", "Voting.json"),
      "utf8",
    ),
  );
  const localContractAddress = votingArtifact.networks?.["1337"]?.address;
  if (!localContractAddress) {
    log(
      prefix.system,
      `${colors.red}Could not find the deployed local Voting contract address.${colors.reset}`,
    );
    cleanup();
    process.exit(1);
  }

  // 3. Start Backend
  const python = findPython();
  const configuredAdminPassword = process.env.ADMIN_PASSWORD?.trim();
  const adminPassword = configuredAdminPassword || randomBytes(24).toString("hex");
  const adminUsername = process.env.ADMIN_USERNAME?.trim() || "admin_user";
  log(
    prefix.system,
    `Starting Python FastAPI backend using [${[python.command, ...python.args].join(" ")}]...`,
  );
  const backendProc = spawnService(
    python.command,
    [
      ...python.args,
      "-m",
      "uvicorn",
      "main:app",
      "--app-dir",
      path.join(rootDir, "server", "face-recognition"),
      "--host",
      "127.0.0.1",
      "--port",
      "8000",
    ],
    {
      cwd: path.join(rootDir, "server", "face-recognition"),
      env: {
        ...process.env,
        ADMIN_USERNAME: adminUsername,
        ADMIN_PASSWORD: adminPassword,
        BLOCKCHAIN_CONTRACT_ADDRESS: localContractAddress,
        BLOCKCHAIN_RELAYER_PRIVATE_KEY:
          "0x4f3edf983ac636a65a842ce7c78d9aa706d3b113bce9c46f30d7d21715b23b1d",
      },
    },
  );
  activeProcesses.push(backendProc);
  pipeOutput(backendProc, prefix.backend);
  backendProc.once("error", (error) => {
    log(
      prefix.backend,
      `${colors.red}Process error: ${error.message}${colors.reset}`,
    );
  });
  backendProc.once("close", (code, signal) => {
    if (code !== null && code !== 0) {
      log(
        prefix.backend,
        `${colors.red}Backend exited with code ${code}${signal ? ` (${signal})` : ""}.${colors.reset}`,
      );
    }
  });

  log(prefix.system, "Waiting for FastAPI health check...");
  try {
    await waitForHttp("http://127.0.0.1:8000/health", backendProc);
    log(prefix.system, "FastAPI backend is ready!");
  } catch (err) {
    log(
      prefix.system,
      `${colors.red}FastAPI backend failed to start: ${err.message}${colors.reset}`,
    );
    cleanup();
    process.exit(1);
  }

  // 4. Start Frontend
  log(prefix.system, "Starting Vite React frontend...");
  const viteCli = resolveCli("vite", path.join("bin", "vite.js"));
  const frontendProc = spawnService(viteCli.command, [...viteCli.args], {
    env: {
      ...process.env,
      // The demo deploys to local Ganache, regardless of Sepolia values in .env.
      VITE_NETWORK_ID: "1337",
      VITE_CONTRACT_ADDRESS: localContractAddress,
      VITE_CONFIG_NATIVE_IGNORE_WARNING: "true",
    },
    isCmd: viteCli.isCmd,
  });
  activeProcesses.push(frontendProc);
  pipeOutput(frontendProc, prefix.frontend);

  console.log(
    `\n${colors.bright}${colors.green}✔ All services are running!${colors.reset}`,
  );
  console.log(
    `  - Frontend: ${colors.cyan}http://localhost:8080${colors.reset}`,
  );
  console.log(
    `  - Backend:  ${colors.cyan}http://localhost:8000${colors.reset}`,
  );
  console.log(
    `  - Ganache:  ${colors.cyan}http://localhost:7545${colors.reset}`,
  );
  if (!configuredAdminPassword) {
    console.log(
      `  - Local demo admin: ${colors.cyan}${adminUsername}${colors.reset} / ${colors.cyan}${adminPassword}${colors.reset}`,
    );
    console.log(
      `    This password is temporary and will change the next time you run the demo.`,
    );
  }
  console.log(
    `\n${colors.yellow}Press Ctrl+C to stop all services.${colors.reset}\n`,
  );
}

main().catch((err) => {
  console.error("Fatal startup error:", err);
  cleanup();
  process.exit(1);
});

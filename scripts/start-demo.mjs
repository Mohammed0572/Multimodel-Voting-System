import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");

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

  if (fs.existsSync(venvWin)) return venvWin;
  if (fs.existsSync(venvUnix)) return venvUnix;
  return process.platform === "win32" ? "python" : "python3";
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
          if (elapsedSec >= 4 && elapsedSec !== lastLoggedSec && elapsedSec % 4 === 0) {
            lastLoggedSec = elapsedSec;
            log(prefix.system, `Still waiting for port ${port} (${elapsedSec}s elapsed)...`);
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

  // 1. Start Ganache
  log(
    prefix.system,
    "Starting Ganache blockchain on port 7545 (networkId 1337)...",
  );
  const ganacheCli = resolveCli("ganache", path.join("dist", "node", "cli.js"));
  const ganacheProc = spawnService(
    ganacheCli.command,
    [
      ...ganacheCli.args,
      "--port",
      "7545",
      "--deterministic",
      "--networkId",
      "1337",
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
    const truffleCli = resolveCli("truffle", path.join("build", "cli.bundled.js"));
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
  const pythonExec = findPython();
  log(
    prefix.system,
    `Starting Python FastAPI backend using [${pythonExec}]...`,
  );
  const backendProc = spawnService(
    pythonExec,
    [
      "-m",
      "uvicorn",
      "main:app",
      "--host",
      "127.0.0.1",
      "--port",
      "8000",
      "--reload",
    ],
    {
      cwd: path.join(rootDir, "server", "face-recognition"),
      env: {
        ...process.env,
        BLOCKCHAIN_CONTRACT_ADDRESS: localContractAddress,
        RESET_VOTING_CREDENTIALS_ON_START: "true",
        BLOCKCHAIN_RELAYER_PRIVATE_KEY:
          "0x4f3edf983ac636a65a842ce7c78d9aa706d3b113bce9c46f30d7d21715b23b1d",
      },
    },
  );
  activeProcesses.push(backendProc);
  pipeOutput(backendProc, prefix.backend);

  // 4. Start Frontend
  log(prefix.system, "Starting Vite React frontend...");
  const viteCli = resolveCli("vite", path.join("bin", "vite.js"));
  const frontendProc = spawnService(viteCli.command, [...viteCli.args], {
    env: {
      ...process.env,
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
  console.log(
    `\n${colors.yellow}Press Ctrl+C to stop all services.${colors.reset}\n`,
  );
}

main().catch((err) => {
  console.error("Fatal startup error:", err);
  cleanup();
  process.exit(1);
});

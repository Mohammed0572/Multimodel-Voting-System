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
  compile: `${colors.cyan}[Compile]${colors.reset} `,
  deploy: `${colors.cyan}[Contract]${colors.reset} `,
  backend: `${colors.magenta}[Backend]${colors.reset} `,
  frontend: `${colors.green}[Frontend]${colors.reset} `,
  system: `${colors.bright}${colors.blue}[System]${colors.reset} `,
};

const activeProcesses = [];

function log(systemPrefix, message) {
  console.log(`${systemPrefix}${message}`);
}

function pipeOutput(child, logPrefix, includeStdout = true) {
  child.stdout?.on("data", (data) => {
    const lines = data.toString().trimEnd().split("\n");
    for (const line of lines) {
      if (includeStdout && line.trim()) console.log(`${logPrefix}${line}`);
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

async function ganacheRpc(method, params = []) {
  const response = await fetch("http://127.0.0.1:7545", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
  });
  if (!response.ok) {
    throw new Error(`Ganache returned HTTP ${response.status} for ${method}.`);
  }
  const result = await response.json();
  if (result.error) {
    throw new Error(
      `Ganache ${method} failed: ${result.error.message || JSON.stringify(result.error)}`,
    );
  }
  return result.result;
}

async function hasDeployedCode(address) {
  const code = await ganacheRpc("eth_getCode", [address, "latest"]);
  return typeof code === "string" && code !== "0x" && code !== "0x0";
}

async function deployVotingContract(relayerAddress, votingArtifact) {
  if (!/^0x[a-fA-F0-9]{40}$/.test(relayerAddress)) {
    throw new Error(`Invalid demo relayer address: ${relayerAddress}`);
  }
  if (!/^0x[0-9a-fA-F]+$/.test(votingArtifact.bytecode || "")) {
    throw new Error("Voting contract bytecode is missing or invalid.");
  }

  const constructorArgument = relayerAddress.slice(2).toLowerCase().padStart(64, "0");
  const data = `${votingArtifact.bytecode}${constructorArgument}`;
  const from = (await ganacheRpc("eth_accounts"))[0];
  if (!from) throw new Error("Ganache did not provide a deployment account.");
  if (from.toLowerCase() !== relayerAddress.toLowerCase()) {
    throw new Error("The demo relayer must be Ganache's first deployment account.");
  }

  const gas = await ganacheRpc("eth_estimateGas", [{ from, data }]);
  const transactionHash = await ganacheRpc("eth_sendTransaction", [
    { from, data, gas },
  ]);
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const receipt = await ganacheRpc("eth_getTransactionReceipt", [
      transactionHash,
    ]);
    if (receipt) {
      if (receipt.status !== "0x1") {
        throw new Error(`Voting contract deployment failed: ${transactionHash}`);
      }
      if (!/^0x[a-fA-F0-9]{40}$/.test(receipt.contractAddress || "")) {
        throw new Error("Ganache returned an invalid deployed contract address.");
      }
      if (!(await hasDeployedCode(receipt.contractAddress))) {
        throw new Error("Voting contract deployment produced no on-chain code.");
      }
      return receipt.contractAddress;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }

  throw new Error(`Timed out waiting for deployment transaction ${transactionHash}.`);
}

async function resolveVotingContractAddress(startNewElection, relayerAddress) {
  const artifactPath = path.join(rootDir, "src", "contracts", "Voting.json");
  const artifact = JSON.parse(fs.readFileSync(artifactPath, "utf8"));
  const electionPath = path.join(rootDir, ".ganache", "current-election.json");
  const knownAddresses = [];

  if (!startNewElection) {
    if (fs.existsSync(electionPath)) {
      const savedElection = JSON.parse(fs.readFileSync(electionPath, "utf8"));
      if (!/^0x[a-fA-F0-9]{40}$/.test(savedElection.address || "")) {
        throw new Error(`Invalid contract address in ${electionPath}.`);
      }
      knownAddresses.push(savedElection.address);
    }
    const artifactAddress = artifact.networks?.["1337"]?.address;
    if (
      /^0x[a-fA-F0-9]{40}$/.test(artifactAddress || "") &&
      !knownAddresses.some(
        (address) => address.toLowerCase() === artifactAddress.toLowerCase(),
      )
    ) {
      knownAddresses.push(artifactAddress);
    }
  }

  for (const address of knownAddresses) {
    if (await hasDeployedCode(address)) {
      fs.writeFileSync(electionPath, `${JSON.stringify({ address }, null, 2)}\n`);
      return address;
    }
  }

  const address = await deployVotingContract(relayerAddress, artifact);
  fs.writeFileSync(electionPath, `${JSON.stringify({ address }, null, 2)}\n`);
  return address;
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
  const startNewElection = process.argv.includes("--new-election");

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

  log(prefix.system, "Compiling smart contracts...");
  const truffleCli = resolveCli(
    "truffle",
    path.join("build", "cli.bundled.js"),
  );
  await runCommand(
    truffleCli.command,
    [
      ...truffleCli.args,
      "compile",
      "--config",
      "server/blockchain/truffle-config.js",
    ],
    rootDir,
    prefix.compile,
    truffleCli.isCmd,
  );

  // 1. Start Ganache
  log(
    prefix.system,
    "Starting Ganache blockchain on port 7545 (networkId 1337)...",
  );
  const ganacheCli = resolveCli("ganache", path.join("dist", "node", "cli.js"));
  const ganacheDataDir = path.join(rootDir, ".ganache", "demo-chain");
  fs.mkdirSync(path.dirname(ganacheDataDir), { recursive: true });
  const accountKeysPath = path.join(rootDir, ".ganache", "demo-account-keys.json");
  const ganacheProc = spawnService(
    ganacheCli.command,
    [
      ...ganacheCli.args,
      "--port",
      "7545",
      "--deterministic",
      "--wallet.accountKeysPath",
      accountKeysPath,
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
  pipeOutput(ganacheProc, prefix.ganache, false);

  log(prefix.system, "Waiting for Ganache blockchain to be ready...");
  await waitForPort(7545);
  log(prefix.system, "Ganache is ready!");
  const demoKeys = JSON.parse(fs.readFileSync(accountKeysPath, "utf8"));
  const [demoRelayer, demoPrivateKey] = Object.entries(demoKeys.private_keys)[0];
  process.env.RELAYER_ADDRESS = demoRelayer;
  const secretPath = path.join(rootDir, ".ganache", "auth-secret");
  if (!fs.existsSync(secretPath)) fs.writeFileSync(secretPath, randomBytes(32).toString("hex"), { mode: 0o600 });
  const demoSecret = process.env.SECRET_KEY || fs.readFileSync(secretPath, "utf8").trim();

  // 2. Reuse the current election contract or deploy the next one.
  log(prefix.system, "Checking the election contract on Ganache...");
  try {
    let localContractAddress = await resolveVotingContractAddress(
      startNewElection,
      demoRelayer,
    );
    log(
      prefix.system,
      `Voting contract ready at ${localContractAddress}.`,
    );
    if (startNewElection) {
      log(prefix.system, "A fresh election contract was deployed.");
    }

    // 3. Start Backend
    const python = findPython();
    log(prefix.system, "Checking the pinned face models...");
    await runCommand(python.command, [...python.args, path.join(rootDir, "server", "face-recognition", "face_models.py")]);
    const configuredAdminPassword = process.env.ADMIN_PASSWORD?.trim();
    const adminUsername = process.env.ADMIN_USERNAME?.trim() || "admin_user";
    const demoAdminPath = path.join(rootDir, ".ganache", "demo-admin.json");
    const savedAdmin = fs.existsSync(demoAdminPath) ? JSON.parse(fs.readFileSync(demoAdminPath, "utf8")) : null;
    const adminPassword = configuredAdminPassword ||
      (savedAdmin?.username === adminUsername ? savedAdmin.password : null) || randomBytes(24).toString("hex");
    if (!configuredAdminPassword) fs.writeFileSync(demoAdminPath,
      JSON.stringify({ username: adminUsername, password: adminPassword }), { mode: 0o600 });
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
          RESET_ACTIVE_ELECTION: startNewElection ? "true" : "false",
          SECRET_KEY: demoSecret,
          SEED_DEMO_ROSTER: "true",
          BLOCKCHAIN_RELAYER_ADDRESS: demoRelayer,
          BLOCKCHAIN_RELAYER_PRIVATE_KEY: demoPrivateKey.startsWith("0x") ? demoPrivateKey : `0x${demoPrivateKey}`,
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

    const electionResponse = await fetch(
      "http://127.0.0.1:8000/api/v1/election",
      { cache: "no-store" },
    );
    if (!electionResponse.ok) {
      throw new Error(
        `Unable to load the active election after backend startup (HTTP ${electionResponse.status}).`,
      );
    }
    const activeElection = await electionResponse.json();
    if (!/^0x[a-fA-F0-9]{40}$/.test(activeElection.contract_address || "")) {
      throw new Error("The backend returned an invalid active election address.");
    }
    localContractAddress = activeElection.contract_address;
    fs.writeFileSync(
      path.join(rootDir, ".ganache", "current-election.json"),
      `${JSON.stringify({ address: localContractAddress }, null, 2)}\n`,
    );

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
        `  - Local demo admin credentials are in ${demoAdminPath} (kept out of logs).`,
      );
    }
    console.log(
      `\n${colors.yellow}Press Ctrl+C to stop all services.${colors.reset}\n`,
    );
  } catch (err) {
    log(
      prefix.system,
      `${colors.red}Demo startup failed: ${err.message}${colors.reset}`,
    );
    cleanup();
    process.exit(1);
  }
}

main().catch((err) => {
  console.error("Fatal startup error:", err);
  cleanup();
  process.exit(1);
});

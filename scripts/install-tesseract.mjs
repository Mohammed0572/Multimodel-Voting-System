import { execSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

function findTesseractBinary() {
  // 1. Try checking standard PATH command
  try {
    const versionOutput = execSync("tesseract --version", {
      encoding: "utf-8",
      stdio: ["pipe", "pipe", "ignore"],
    });
    const firstLine = versionOutput.trim().split("\n")[0];
    let resolvedPath = "PATH";
    try {
      const whichCmd = os.platform() === "win32" ? "where tesseract" : "which tesseract";
      resolvedPath = execSync(whichCmd, { encoding: "utf-8", stdio: ["pipe", "pipe", "ignore"] }).trim().split("\n")[0];
    } catch {
      // Keep fallback
    }
    return { installed: true, location: resolvedPath, version: firstLine };
  } catch {
    // Continue to fallback checks
  }

  // 2. Windows specific fallback locations
  if (os.platform() === "win32") {
    const commonWinPaths = [
      "C:\\Program Files\\Tesseract-OCR\\tesseract.exe",
      "C:\\Program Files (x86)\\Tesseract-OCR\\tesseract.exe",
      path.join(process.env.LOCALAPPDATA || "", "Programs", "Tesseract-OCR", "tesseract.exe"),
      path.join(process.env.USERPROFILE || "", "AppData", "Local", "Programs", "Tesseract-OCR", "tesseract.exe"),
    ];

    for (const binPath of commonWinPaths) {
      if (binPath && fs.existsSync(binPath)) {
        try {
          const versionOutput = execSync(`"${binPath}" --version`, {
            encoding: "utf-8",
            stdio: ["pipe", "pipe", "ignore"],
          });
          const firstLine = versionOutput.trim().split("\n")[0];
          // Temporarily append directory to process PATH environment
          const binDir = path.dirname(binPath);
          process.env.PATH = `${binDir};${process.env.PATH}`;
          return { installed: true, location: binPath, version: firstLine };
        } catch {
          // Ignore error and try next path
        }
      }
    }
  }

  return { installed: false };
}

function installTesseract() {
  const result = findTesseractBinary();

  if (result.installed) {
    console.log(`[+] Tesseract OCR is already installed (${result.version}).`);
    console.log(`[+] Found at: ${result.location}`);
    console.log("[+] Skipping installation step.");
    return;
  }

  console.log("[!] Tesseract OCR was not found on your system.");
  console.log("[*] Attempting automated installation of Tesseract OCR...");

  const platform = os.platform();

  if (platform === "win32") {
    try {
      console.log("[*] Installing Tesseract OCR via winget...");
      execSync(
        "winget install --id UB-Mannheim.TesseractOCR --accept-source-agreements --accept-package-agreements",
        { stdio: "inherit" }
      );
      console.log("[+] Tesseract OCR installed successfully via winget.");
      console.log("[!] Note: You may need to restart your terminal for PATH changes to take full effect.");
      return;
    } catch {
      console.log("[!] winget installation failed or unavailable. Trying choco...");
    }

    try {
      execSync("choco install tesseract -y", { stdio: "inherit" });
      console.log("[+] Tesseract OCR installed successfully via choco.");
      console.log("[!] Note: You may need to restart your terminal for PATH changes to take full effect.");
      return;
    } catch {
      console.error(
        "[X] Error: Could not automatically install Tesseract on Windows.\n" +
          "    Please download and install Tesseract manually from:\n" +
          "    https://github.com/UB-Mannheim/tesseract/wiki"
      );
      process.exit(1);
    }
  } else if (platform === "darwin") {
    try {
      console.log("[*] Installing Tesseract OCR via Homebrew...");
      execSync("brew install tesseract", { stdio: "inherit" });
      console.log("[+] Tesseract OCR installed successfully via brew.");
    } catch (err) {
      console.error(`[X] Failed to install Tesseract via Homebrew: ${err.message}`);
      process.exit(1);
    }
  } else if (platform === "linux") {
    const pkgManagers = [
      { cmd: "sudo apt-get update && sudo apt-get install -y tesseract-ocr", check: "apt-get" },
      { cmd: "sudo dnf install -y tesseract", check: "dnf" },
      { cmd: "sudo pacman -S --noconfirm tesseract", check: "pacman" },
      { cmd: "sudo apk add tesseract-ocr", check: "apk" },
    ];

    let installed = false;
    for (const pm of pkgManagers) {
      try {
        execSync(`command -v ${pm.check}`, { stdio: "ignore" });
        console.log(`[*] Installing Tesseract using ${pm.check}...`);
        execSync(pm.cmd, { stdio: "inherit" });
        installed = true;
        break;
      } catch {
        continue;
      }
    }

    if (!installed) {
      console.error(
        "[X] Could not find a supported package manager (apt-get, dnf, pacman, apk).\n" +
          "    Please install Tesseract manually using your distribution package manager."
      );
      process.exit(1);
    }
  } else {
    console.error(`[X] Unsupported operating system: ${platform}`);
    process.exit(1);
  }
}

installTesseract();

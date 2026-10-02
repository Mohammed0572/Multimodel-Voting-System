# Contributing to Multimodal Voting System

Thank you for your interest in contributing to the **Multimodal Voting System**! We welcome contributions from the community to help make digital voting more secure, accessible, and transparent.

Please take a few moments to review these guidelines before submitting an issue or pull request.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How Can I Contribute?](#how-can-i-contribute)
  - [Reporting Bugs](#reporting-bugs)
  - [Suggesting Enhancements](#suggesting-enhancements)
  - [Contributing Code](#contributing-code)
- [Development Setup](#development-setup)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Environment Variables](#environment-variables)
  - [Running the Application](#running-the-application)
- [Testing & Quality Assurance](#testing--quality-assurance)
  - [Linting & Formatting](#linting--formatting)
  - [Running Tests](#running-tests)
- [Git Workflow & Commit Guidelines](#git-workflow--commit-guidelines)
  - [Branch Naming](#branch-naming)
  - [Commit Messages](#commit-messages)
  - [Pull Request Process](#pull-request-process)
- [Security Vulnerabilities](#security-vulnerabilities)

---

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](./CODE_OF_CONDUCT.md). Please report unacceptable behavior to the project maintainers.

---

## How Can I Contribute?

### Reporting Bugs

Before creating a bug report, please check existing issues to ensure the problem hasn't already been reported.

When opening an issue, provide:

- A clear and descriptive title.
- Steps to reproduce the problem.
- Expected behavior vs. actual behavior.
- Relevant logs, error outputs, or screenshots.
- Details about your environment (OS, Node.js version, Python version, browser).

### Suggesting Enhancements

Enhancement suggestions are welcome! Please submit an issue describing:

- The problem you want solved or the feature you'd like added.
- The proposed solution and potential alternatives.
- Context on how this benefits users and aligns with the project's goals.

### Contributing Code

1. Find an open issue or open one to discuss the changes you plan to make.
2. Fork the repository and create a descriptive branch for your work.
3. Make your changes adhering to existing code conventions.
4. Ensure all tests and linters pass.
5. Submit a pull request.

---

## Development Setup

### Prerequisites

Make sure you have the following installed on your machine:

- **Node.js**: v18.0.0 or later (v20+ recommended)
- **pnpm**: Recommended package manager (`npm install -g pnpm`)
- **Python**: 3.9+ (for the face-recognition backend service)
- **Git**
- _(Optional)_ **Tesseract OCR**: Required for local OCR processing features.
- _(Optional)_ **Docker & Docker Compose**: For containerized deployment testing.

### Installation

1. Clone your fork:

   ```bash
   git clone https://github.com/<your-username>/Multimodel-Voting-System.git
   cd Multimodel-Voting-System
   ```

2. Install Node.js dependencies:

   ```bash
   pnpm install
   ```

3. Set up the Python virtual environment for the face recognition service:

   ```bash
   # On Windows (PowerShell):
   python -m venv server/face-recognition/.venv
   server/face-recognition/.venv\Scripts\Activate.ps1
   pip install -r server/face-recognition/requirements.txt

   # On Linux / macOS:
   python3 -m venv server/face-recognition/.venv
   source server/face-recognition/.venv/bin/activate
   pip install -r server/face-recognition/requirements.txt
   ```

Alternatively, if you have `make` installed:

```bash
make install
```

### Environment Variables

Copy the example environment files and configure required variables:

```bash
cp .env.example .env
```

Review `.env` and fill in necessary keys and configurations (e.g., blockchain RPC URLs, secret keys).

### Running the Application

- **Frontend (Vite + React)**:
  ```bash
  pnpm dev
  ```
- **Local Blockchain (Ganache)**:
  ```bash
  npx ganache --port 7545
  ```
- **Compile & Migrate Smart Contracts**:
  ```bash
  pnpm compile:contracts
  npx truffle migrate --reset --network development
  ```
- **Face Recognition Backend (FastAPI)**:
  ```bash
  python server/face-recognition/main.py
  ```
- **Run Full Local Stack Demo**:
  ```bash
  pnpm demo
  # Or with Makefile:
  make demo
  ```

---

## Testing & Quality Assurance

All pull requests must pass automated lint checks and existing tests.

### Linting & Formatting

Run ESLint before committing:

```bash
pnpm lint
```

### Running Tests

- **Frontend unit tests (Vitest)**:

  ```bash
  pnpm test
  # Or:
  make test-frontend
  ```

- **Smart contract tests (Truffle)**:

  ```bash
  pnpm test:blockchain
  # Or:
  make test-contracts
  ```

- **Backend tests (Pytest)**:

  ```bash
  pytest server/face-recognition/tests
  # Or:
  make test-backend
  ```

- **Run all test suites**:
  ```bash
  make test
  ```

---

## Git Workflow & Commit Guidelines

### Branch Naming

Create feature or fix branches branching off `master`:

- `feat/feature-name`
- `fix/bug-description`
- `docs/documentation-update`
- `refactor/component-name`
- `test/test-suite-name`

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

- `feat: add biometric voter verification step`
- `fix: resolve token expiration handling in auth modal`
- `docs: update deployment instructions in README`
- `test: add unit tests for ballot casting contract`
- `chore: update dependencies`

Keep commit messages concise, imperative, and descriptive.

### Pull Request Process

1. Keep PRs focused on a single feature, bug fix, or refactor.
2. Update relevant documentation (`README.md`, `docs/`, etc.) if your change alters behavior or configuration.
3. Ensure no unwanted files (e.g., `.env`, cache files, build outputs) are committed.
4. Fill out the PR description with:
   - Summary of changes.
   - Related issue numbers (`Fixes #123`).
   - Instructions on how reviewers can test your changes.
5. Maintainers will review your PR and provide feedback. Address any review comments promptly.

---

## Security Vulnerabilities

If you discover a security vulnerability, please **do not** open a public issue. Refer to our [Security Policy](./SECURITY.md) to report vulnerabilities privately.

---

Thank you for contributing to the Multimodal Voting System!

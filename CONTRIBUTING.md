# Contributing to XAUUSD AI Trading Bot

Thank you for your interest in contributing to **XAUUSD AI Trading Bot**! We welcome contributions from developers, quantitative traders, data scientists, and open-source enthusiasts.

Please take a moment to review this document to ensure a smooth contribution process.

---

## 📋 Table of Contents

1. [Code of Conduct](#-code-of-conduct)
2. [How to Contribute](#-how-to-contribute)
   - [Reporting Bugs](#reporting-bugs)
   - [Suggesting Features](#suggesting-features)
   - [Submitting Pull Requests](#submitting-pull-requests)
3. [Development Setup](#-development-setup)
4. [Testing & Quality Assurance](#-testing--quality-assurance)
5. [Code Style & Standards](#-code-style--standards)
6. [Financial & Trading Disclaimer](#-financial--trading-disclaimer)

---

## 📜 Code of Conduct

This project adheres to the Contributor Covenant [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold these standards.

---

## 🚀 How to Contribute

### Reporting Bugs

Before creating a bug report, please check existing issues to avoid duplicates. When filing an issue, please include:
- A clear and descriptive title.
- Detailed steps to reproduce the issue.
- Expected behavior vs. actual behavior.
- Relevant log output (with sensitive API keys/credentials redacted).
- System information (OS version, MetaTrader 5 version, Python version).

### Suggesting Features

Feature requests are highly encouraged! Please describe:
- The trading strategy, ML model enhancement, or system feature you would like added.
- Why this enhancement would benefit the project.
- Any potential risks or edge cases (e.g., execution latency, slippage, market regimes).

### Submitting Pull Requests

1. **Fork** the repository and create a new feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. Make your changes adhering to our coding standards.
3. Write or update tests covering your changes.
4. Run the test suite to ensure all tests pass:
   ```bash
   pytest
   ```
5. Commit your changes with concise, descriptive commit messages:
   ```bash
   git commit -m "feat(strategy): add momentum-filter for XAUUSD regime detection"
   ```
6. Push to your fork and open a **Pull Request** against `main`.

---

## 🛠️ Development Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Mazonia/xau-traderbot.git
   cd xau-traderbot
   ```

2. **Set up a Python virtual environment:**
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On Linux/macOS:
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Configuration:**
   Copy `.env.example` (if present) or configure your environment variables for local testing (e.g., MT5 credentials, Telegram bot keys, Gemini API key). Never commit actual secrets or credentials!

---

## 🧪 Testing & Quality Assurance

We use `pytest` for unit and integration testing.

- Run all tests:
  ```bash
  pytest
  ```
- Run tests with coverage:
  ```bash
  pytest --cov=.
  ```
- Ensure all automated tests pass before submitting your PR.

---

## 🎨 Code Style & Standards

- **Python Version**: Python 3.10+
- **Style Guide**: Follow [PEP 8](https://peps.python.org/pep-0008/) conventions.
- **Type Annotations**: Use type hints for function signatures wherever possible.
- **Docstrings**: Provide clear docstrings for classes and non-trivial functions (Google style preferred).
- **Security**: Never hardcode private keys, MT5 passwords, or webhook secret tokens.

---

## ⚠️ Financial & Trading Disclaimer

This software is developed for educational, research, and algorithmic trading experimentation purposes. Trading spot gold (XAUUSD) or leveraged financial instruments involves substantial risk of loss. Contributions involving order execution, risk management, or position sizing must be carefully tested in demo environments prior to deployment.

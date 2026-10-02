# Security Policy

## 🛡️ Supported Versions

We actively issue security updates and patches for the following versions of **XAUUSD AI Trading Bot**:

| Version | Supported          |
| ------- | ------------------ |
| 3.x.x   | :white_check_mark: |
| < 3.0.0 | :x:                |

---

## 🔒 Reporting a Vulnerability

We take the security of this software very seriously, particularly because it manages algorithmic trading operations, API keys, and market execution.

### How to Report

If you discover a security vulnerability, **please do not open a public issue**. Instead, submit a security report directly to the maintainers:

- Alternatively, submit a private vulnerability disclosure via GitHub Security Advisories if available on the repository.

### What to Include in Your Report

To help us investigate and address the vulnerability effectively, please include:
1. A descriptive title and type of vulnerability (e.g., credential exposure, SQL injection, buffer overflow, unvalidated endpoint).
2. Step-by-step instructions or proof-of-concept code to reproduce the issue.
3. Potential impact of the vulnerability.
4. Any suggested remediations or patches, if available.

### Disclosure Process & Timeline

1. **Acknowledgment**: We will acknowledge receipt of your vulnerability report within **48 hours**.
2. **Assessment**: The maintainers will investigate the vulnerability, assess its severity, and determine an appropriate fix.
3. **Fix & Patch**: We aim to release a patch or mitigation within **7 to 14 days** of verification, depending on complexity.
4. **Public Announcement**: Once a fix is deployed, we will publish a release note and credit the reporter (unless anonymity is requested).

---

## 🔐 Security Best Practices for Operators

When running **XAUUSD AI Trading Bot** in production or live environments:

1. **Protect Credentials**: Store MetaTrader 5 credentials, Telegram bot tokens, Gemini API keys, and database passwords strictly in environment variables or a `.env` file. Never commit credentials to version control.
2. **Dashboard Security**: Ensure the web dashboard and WebSocket endpoints are secured behind HTTPS and protected by strong authentication when hosted on public or non-trusted networks.
3. **Network Isolation**: Run the MT5 bridge and trading bot scripts in restricted network environments with minimal necessary open ports.
4. **Regular Updates**: Keep Python dependencies and the underlying MetaTrader 5 terminal updated to their latest stable releases.

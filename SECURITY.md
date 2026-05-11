# Security Policy

## Supported Versions

Security updates are provided for the following versions of DeskAgent:

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x (latest) | Yes |
| 0.9.x (previous minor) | Yes |
| Older versions | No |

We strongly recommend always running the latest released version.

## Reporting a Vulnerability

**Please do NOT open a public GitHub issue for security vulnerabilities.**

If you believe you have found a security vulnerability in DeskAgent, please
report it privately by emailing:

**security@realvirtual.io** (or, if that is not yet set up: **info@realvirtual.io**)

Please include in your report:

- A clear description of the issue
- Steps to reproduce or a proof-of-concept
- The DeskAgent version affected
- The platform (Windows / macOS / Linux)
- Your assessment of impact (data exposure, RCE, privilege escalation, etc.)
- Whether the issue is already public knowledge or remains undisclosed

If possible, please encrypt sensitive details using our PGP key (available
on request).

## Response Timeline

We follow Coordinated Disclosure principles:

| Stage | Target |
|-------|--------|
| Acknowledgement of report | Within 48-72 hours |
| Initial assessment and severity rating | Within 7 days |
| Patch development | Within 30 days for high-severity issues |
| Coordinated public disclosure | Mutually agreed timeline, typically 90 days |

We will keep you informed of progress and credit you appropriately upon
public disclosure (unless you prefer to remain anonymous).

## Scope

The following components are in scope for security reports:

- DeskAgent core (FastAPI server, agent execution, MCP servers in this repo)
- Configuration handling, encryption, license validation
- IPC mechanisms, plugin loading
- Anonymization proxy and PII handling

Out of scope:

- Vulnerabilities in third-party dependencies (please report those upstream)
- Issues that require physical access to the user's machine
- Self-inflicted misconfigurations (e.g. running with `0.0.0.0` exposed
  to the internet without authentication)

## Hall of Fame

Researchers who have responsibly disclosed vulnerabilities to us:

*(none yet — be the first!)*

## Bug Bounty

We do not currently operate a paid bug bounty program. We do publicly
acknowledge contributions and may offer DeskAgent merchandise or extended
Commercial License terms as a token of appreciation for significant
findings.

---

**Contact:** info@realvirtual.io
**Last updated:** 2026-05-09

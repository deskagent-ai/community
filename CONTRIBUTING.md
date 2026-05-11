# Contributing to DeskAgent

DeskAgent is open source under AGPL-3.0 with a Plugin Exception. Issues,
discussions, and pull requests are welcome. Please note that this is a
small project — there are no guarantees about response or merge times.

## Be respectful

Treat other contributors with respect. We don't have a formal Code of
Conduct because we trust adults to behave like adults. Discriminatory,
harassing, or abusive behavior will result in being blocked from the
project. Report problems to **info@realvirtual.io**.

## How contributions are licensed

By submitting a pull request, you confirm that:

- The contribution is your original work (or you have the right to submit it).
- You license your contribution under the AGPL-3.0 license used by this project.
- You grant realvirtual GmbH a non-exclusive, perpetual right to also use your
  contribution under a commercial license, so that DeskAgent can continue to
  offer dual-licensing (AGPL-3.0 for the community, Commercial License for
  customers who need AGPL exemption).

This is an inline statement — there is no separate CLA document to sign.
For larger contributions a more formal agreement may be requested.

## Setup

Requirements: Python 3.12 and Git.

```bash
git clone https://github.com/deskagent-ai/community.git deskagent
cd deskagent

# macOS / Linux
./setup-unix.sh

# Windows
setup-python.bat

# Optional extras
pip install -e .[anonymizer]
pip install -e .[claude-sdk]
```

Run the WebUI:

```bash
./start.sh    # macOS / Linux
start.bat     # Windows
```

Open http://localhost:8765/ in your browser.

## Development workflow

1. Fork the repository and create a topic branch
   (`git checkout -b feat/short-description`).
2. Make your changes. Keep commits focused and small.
3. Add or update tests under `scripts/tests/` (we use `pytest`).
4. Run the test suite locally:

   ```bash
   python -m pytest scripts/tests/ -x --tb=short
   ```

5. Update relevant documentation in `knowledge/`.
6. Open a pull request.

## Coding standards

- **Language:** Python 3.12 (do not use 3.13-only features; do not go below 3.10).
- **Type hints** on new public functions.
- **Imports:** absolute imports inside `scripts/` (the start scripts add
  `scripts/` to `PYTHONPATH`).
- **No emoji** in source code, log messages, or commit messages.
- **No comments** explaining what the code does. Comment only when the *why*
  is not obvious.
- **Conventional commits**: `feat(scope):`, `fix(scope):`, `docs(scope):`,
  `refactor(scope):`, `test(scope):`, `chore(scope):`.

## License headers

New `.py` files need the AGPL-3.0 header:

```python
# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.
```

## Reporting security issues

Do NOT open a public GitHub issue. See [SECURITY.md](SECURITY.md).

---

For questions, open a GitHub Discussion.

# Contributing to DAMnation

Thanks for your interest in DAMnation. This document covers how to get set up for development, how to submit issues and pull requests, and what contributors should know about the project's license structure.

## The reference implementation

DAMnation was built to power [Hokai](https://hokaiprime.com), an original AI-generated sci-fi series. Hokai is the reference implementation — if something works in production for Hokai, it works. Bug reports and PRs that include real-world reproduction cases are prioritized over theoretical ones.

## Getting started

```bash
git clone https://github.com/sjmcgra/damnation.git
cd damnation
cp .env.example .env
# Edit .env with your paths
./install.sh
source .venv/bin/activate
```

For the web UI:

```bash
docker compose up --build -d
```

See README.md for the full setup walkthrough, including the host/container architecture and how the indexer and DVC tooling relate to the web UI.

## Submitting issues

Before opening an issue:
- Check that your `.env` is configured correctly (the most common source of problems)
- Check the Docker logs: `docker logs damnation-dam-web-1`
- Check that `DB_DATA_PATH` in `.env` uses an absolute path (no `~` or `$HOME`)

When filing a bug, include:
- Your OS and Python version
- The relevant section of your `.env` (redact credentials)
- The full error output
- What you expected to happen

## Submitting pull requests

The standard GitHub fork-and-PR workflow applies:

1. Fork `sjmcgra/damnation` to your own GitHub account
2. Create a feature branch in your fork: `git checkout -b fix/my-fix`
3. Make your changes and push to your fork
4. Open a Pull Request from your branch to `sjmcgra/damnation/main`

You do not need write access to the repo to contribute. GitHub's fork model handles it.

- Open an issue first for anything non-trivial so we can discuss approach before you invest time
- Keep PRs focused — one thing per PR
- Add the GPL boilerplate header to any new `.py` or `.sh` files you create (copy from any existing file)
- Test against a real project directory, not just synthetic data

## License and contributor agreement

DAMnation is dual-licensed:

- **Community Edition**: GNU General Public License v3.0 (GPL-3.0). This is what you are contributing to when you submit a PR.
- **Studio Edition**: A proprietary version with additional features is planned. 

By submitting a pull request, you agree that your contribution may be included in both the GPL-licensed Community Edition and the proprietary Studio Edition. If you are not comfortable with this, please say so in your PR and we will discuss alternatives.

The full GPL-3.0 license text is in [LICENSE](LICENSE).

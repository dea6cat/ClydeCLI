# Contributing to ClydeCLI

Thank you for your interest in contributing to ClydeCLI! This document provides guidelines and instructions for contributing.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Coding Standards](#coding-standards)
- [Commit Guidelines](#commit-guidelines)
- [Pull Request Process](#pull-request-process)
- [Testing](#testing)

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](https://www.contributor-covenant.org/version/2/0/code_of_conduct/). By participating, you are expected to uphold this code. Please report unacceptable behavior to the project maintainers.

## Development Setup

### Prerequisites

- Python 3.14 or higher
- `uv` (recommended) or `pip`
- git
- An API key for at least one provider, or a local Ollama install (tests need neither)

### Initial Setup

1. **Fork and clone the repository**

```bash
# Fork the repo on GitHub, then:
git clone https://github.com/YOUR_USERNAME/ClydeCLI.git
cd ClydeCLI
```

2. **Create a virtual environment**

```bash
uv venv --python 3.14
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. **Install dependencies**

```bash
uv pip install -r requirements.txt
uv pip install -e ".[dev]"
```

4. **Install development tools**

```bash
uv pip install black isort mypy pytest
```

5. **Configure your API key**

```bash
python -m src.cli login
# or export a provider key, e.g. OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY
```

6. **Run tests to verify setup**

```bash
python -m pytest tests/ -q
```

## Project Structure

```
ClydeCLI/
├── src/                    # Source code
│   ├── providers/         # LLM provider implementations
│   ├── repl/              # Interactive REPL
│   ├── agent/             # Session management
│   ├── skills/            # SKILL.md loading and creation
│   ├── tool_system/       # Tool registry, loop, validation
│   ├── config.py          # Configuration management
│   └── cli.py             # CLI commands
├── tests/                 # Test files
├── .github/               # GitHub workflows and templates
├── requirements.txt       # Python dependencies
├── pyproject.toml         # Project metadata
└── README.md              # Project overview
```

### Key Modules

- **`src/providers/`**: LLM providers, stdlib HTTP only (no vendor SDKs)
  - `types.py`: canonical conversation types every adapter serializes from
  - `base.py`: `Provider` protocol, `ProviderResponse`/`ProviderError`, HTTP helpers, retry, cancellation
  - `openai_compat.py`: one adapter for every OpenAI-compatible service
  - `anthropic.py`, `google.py`, `ollama.py`: adapters for the other wire formats
  - `registry.py`: the provider table and `provider:model` resolution
  - `keys.py`: API keys (env vars + `~/.clyde/keys.json`)
  - `convert.py`: stored conversation <-> canonical types

  Adding an OpenAI-compatible provider is one row in `registry._OPENAI_COMPAT` plus its env var
  in `keys.PROVIDER_KEY_ENV`.

- **`src/repl/`**: Interactive REPL implementation
  - `core.py`: Main REPL logic

- **`src/agent/`**: Session and conversation management
  - `session.py`: Session persistence
  - `conversation.py`: Message history

- **`src/config.py`**: Configuration management
  - Load/save `~/.clyde/config.json` (default model, session settings)
  - One-time migration of the old per-provider config

- **`src/cli.py`**: CLI command implementations

## Coding Standards

### Python Style Guide

We follow PEP 8 with a few modifications:

- **Line length**: 88 characters (Black default)
- **Quotes**: Double quotes for strings, single quotes for dict keys
- **Imports**: Sorted with isort

### Type Hints

**All public functions must have type hints.**

```python
# Good
def resolve(reg: dict[str, Provider], model: str) -> tuple[Provider, str] | None:
    """Resolve a model string to (provider, model)."""
    ...

# Bad
def resolve(reg, model):
    ...
```

### Docstrings

Use Google-style docstrings for all public functions and classes:

```python
def calculate_cost(tokens: int, model: str) -> float:
    """Calculate the cost for a given number of tokens.

    Args:
        tokens: Number of tokens used.
        model: Model name to determine pricing.

    Returns:
        Total cost in USD.

    Raises:
        ValueError: If model is not recognized.
    """
    pass
```

### Code Formatting

We use **Black** for code formatting and **isort** for import sorting:

```bash
# Format code
black src/ tests/

# Sort imports
isort src/ tests/

# Or both at once
black src/ tests/ && isort src/ tests/
```

### Type Checking

We use **mypy** for static type checking:

```bash
mypy src/
```

Aim for zero mypy errors in new code.

## Commit Guidelines

We follow [Conventional Commits](https://www.conventionalcommits.org/):

### Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

### Examples

```bash
feat(repl): add tab completion support
fix(provider): handle API rate limiting correctly
docs(readme): update installation instructions
test(config): add tests for API key encoding
```

### Commit Message Rules

1. Use imperative mood ("add feature" not "added feature")
2. Keep the first line under 72 characters
3. Reference issues and PRs in the footer
4. Write clear, descriptive commit messages

## Pull Request Process

### Before Submitting

1. **Create a feature branch**

```bash
git checkout -b feature/your-feature-name
```

2. **Make your changes**

- Write clean, well-documented code
- Add tests for new functionality
- Ensure all tests pass

3. **Run quality checks**

```bash
# Format code
black src/ tests/
isort src/ tests/

# Type check
mypy src/

# Run tests
python -m pytest tests/ -q

# Test your changes manually
python -m src.cli
```

4. **Commit your changes**

```bash
git add .
git commit -m "feat: your feature description"
```

5. **Push to your fork**

```bash
git push origin feature/your-feature-name
```

### Submitting the PR

1. Go to GitHub and create a Pull Request
2. Fill in the PR template
3. Link any related issues
4. Request review from maintainers

### PR Requirements

- All tests must pass
- Code must be formatted with Black and isort
- No mypy errors
- New code must have type hints and docstrings
- New features must have tests
- Documentation must be updated (if applicable)

### Review Process

1. At least one maintainer must approve
2. All CI checks must pass
3. No merge conflicts
4. PR will be squashed and merged

## Testing

### Running Tests

```bash
# Run all tests
python -m pytest tests/ -q

# Run specific test file
python -m pytest tests/tool_system/test_tool_system_tools.py -q

# Run with coverage
python -m pytest tests/ --cov=src --cov-report=html
```

### Writing Tests

We use **pytest** for testing:

```python
def test_default_model_roundtrip(tmp_path, monkeypatch):
    """Config persistence, isolated from the real home directory."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    from src.config import get_default_model, set_default_model

    set_default_model("openai:gpt-5.4")
    assert get_default_model() == "openai:gpt-5.4"
```

For anything that talks to a model, use the scripted provider in `tests/fakes.py` instead of the
network:

```python
from tests.fakes import FakeProvider, reply

provider = FakeProvider(reply("Hello"))   # queue replies (or exceptions) in order
# ... run code under test ...
assert provider.requests[0]["model"] == "fake-model"
```

### Test Guidelines

1. **Test file naming**: `test_<module>.py`
2. **Test function naming**: `test_<description>`
3. **One test per concern**: Keep tests focused
4. **Use fixtures**: For common setup
5. **Test edge cases**: Not just happy paths
6. **Make tests independent**: No test should depend on another

## Questions?

If you have questions, feel free to:

- Open an issue on GitHub
- Start a discussion in the Discussions tab
- Reach out to maintainers

Thank you for contributing to ClydeCLI!

## Releasing

The `stable` update channel follows release tags. To cut a release: bump `__version__` in `src/__init__.py` (and `version` in
`pyproject.toml`), update `CHANGELOG.md`, merge to `main`, then tag that commit `vX.Y.Z` (for example `git tag v0.2.0 && git push
origin v0.2.0`). Only plain `vX.Y.Z` tags count; others (`v1.0.0-rc1`, `nightly`) are ignored. Until the first tag exists, `clyde
update --channel stable` reports that there is no release yet.

## Releasing

From a clean `main` that matches `origin/main`, with the changes listed under `[Unreleased]` in `CHANGELOG.md`:

```bash
scripts/release.sh patch      # or minor, major, or an exact X.Y.Z
```

It bumps the version in `pyproject.toml`, `src/__init__.py` and `uv.lock`, turns `[Unreleased]` into the new release, commits `Release vX.Y.Z`, tags it and pushes `main` and the tag. Run the tests first; the script does not.

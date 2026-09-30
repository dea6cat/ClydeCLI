# Testing Guide

This document describes the testing strategy and how to run tests for ClydeCLI.

## Test Structure

```
tests/
├── fakes.py                     # scripted FakeProvider used instead of the network
├── fixtures/                    # saved HTML/JSON used by parser tests
├── test_agent_loop.py           # tool loop, streaming, retries, reasoning replay
├── test_provider_layer.py       # converter, registry, usage parsing, tool-call repair
├── test_provider_errors.py      # HTTP error -> readable message
├── test_model_listing.py        # live model lists, caching, filtering
├── test_retry.py / test_cancel_streaming.py / test_abort_connections.py
├── test_reasoning_*.py / test_thinking_*.py   # per-provider reasoning fields
├── test_anthropic_streaming.py / test_google_streaming.py / test_prompt_cache.py
├── test_config.py               # config.json, legacy migration, key store
├── test_cli_login.py            # login flow
├── test_repl.py                 # REPL commands, /model, /think, error handling
└── ...                          # tools, skills, commands, context, compaction
```

## Running Tests

### Run All Tests

```bash
# Activate the project environment first
source .venv/bin/activate

# Using pytest (recommended)
python -m pytest tests/ -q

# Using unittest
python -m unittest discover -s tests -v
```

### Run Specific Test File

```bash
# Test configuration
python -m pytest tests/test_config.py -q

# Test the provider layer
python -m pytest tests/test_provider_layer.py tests/test_model_listing.py -q

# Test REPL
python -m pytest tests/test_repl.py -q

# Test context and agent loop
python -m pytest tests/test_context_system.py tests/test_agent_loop.py -q
```

### Run Specific Test

```bash
# Run specific test by name
python -m pytest tests/test_config.py::TestLegacyMigration::test_keys_move_to_keys_file_decoded -v

# Run tests matching pattern
python -m pytest tests/ -k "reasoning" -v
```

### Run with Coverage

```bash
# Install coverage tool
uv pip install pytest-cov

# Run tests with coverage report
python -m pytest tests/ --cov=src --cov-report=html

# Open coverage report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

## Test Categories

### 1. Configuration Tests (`test_config.py`)

- **Config file**: location, defaults, save/load round trip, 0600 permissions
- **Default model**: `provider:model` get/set
- **Legacy migration**: old per-provider keys move to `keys.json`, the default model carries over
- **Key store**: env vars win over saved keys, connect/disconnect, masking

Each test runs against a throwaway `HOME`, never your real `~/.clyde`.

### 2. Provider Tests

Adapters are tested by patching their HTTP helper (`post_stream` / `post_json`) and asserting on
the exact JSON payload they build and how they parse the provider's SSE/NDJSON reply. Nothing
touches the network.

```python
def test_anthropic_system_prompt_is_cached(self):
    captured = {}

    def fake_post(url, payload, **k):
        captured["p"] = payload
        return {"content": [{"type": "text", "text": "ok"}]}

    with patch.object(anthropic, "post_json", fake_post), patch.dict(os.environ, {"ANTHROPIC_API_KEY": "x"}):
        AnthropicProvider().send(Conversation(system_prompt="SYS"), "claude-sonnet-5", ())
    self.assertEqual(captured["p"]["system"][-1]["cache_control"], {"type": "ephemeral"})
```

Code above the provider layer (agent loop, REPL, compaction) uses `tests/fakes.py`:
`FakeProvider(reply("text"), reply(tool_calls=[("Read", {...})]), SomeError(...))` replays those in
order and records every request in `provider.requests`.

### 3. REPL Tests (`test_repl.py`)

Tests for interactive REPL:

- **REPL Initialization**: Test REPL setup
- **Command Handling**: Test slash commands
- **Session Management**: Test save/load sessions
- **Conversation**: Test message management
- **Multiline Mode**: Test multiline input

**Example:**
```python
def test_handle_command_multiline_toggle(self):
    """Test /multiline command."""
    repl = ClydeREPL(model="glm:glm-4.5")   # inside _fake_provider_env()

    # Initially False
    assert repl.multiline_mode is False

    # Toggle to True
    repl.handle_command("/multiline")
    assert repl.multiline_mode is True

    # Toggle back to False
    repl.handle_command("/multiline")
    assert repl.multiline_mode is False
```

### 4. Porting Workspace Tests (`test_porting_workspace.py`)

Tests for porting completeness:

- **Manifest**: Test file and module counts
- **Query Engine**: Test summary generation
- **CLI Commands**: Test command execution
- **Parity Audit**: Test coverage verification
- **Session Tracking**: Test turn state

## Test Strategy

### Unit Tests
- Test individual functions and classes
- Mock external dependencies (API calls)
- Fast execution (< 1 second per test)
- Independent and isolated

### Integration Tests
- Test component interactions
- Use real API keys only in CI/CD (with secrets)
- Longer execution time
- May require cleanup

### End-to-End Checks
- Test complete workflows in the real REPL
- Currently performed manually for provider login, REPL interaction, skills, and context behavior
- Useful when validating prompt behavior or CLI UX changes

## Writing Tests

### Test Naming Convention

```python
def test_<what_is_being_tested>(self):
    """Test description."""
    pass
```

### Test Structure (AAA Pattern)

```python
def test_feature(self):
    # Arrange - Set up test data
    config = {"model": "openai:gpt-5.4"}

    # Act - Execute the code
    save_config(config)
    loaded = load_config()

    # Assert - Verify results
    assert loaded["model"] == "openai:gpt-5.4"
```

### Best Practices

1. **One assertion per test** (when practical)
2. **Use descriptive test names**
3. **Test edge cases and error conditions**
4. **Keep tests independent**
5. **Use fixtures for common setup**
6. **Mock external dependencies**

### Example Test with a Scripted Provider

```python
def test_tool_call_round_trip(self):
    # Arrange
    provider = FakeProvider(
        reply(tool_calls=[("Read", {"file_path": str(path)}, "t1")]),
        reply("done"),
    )

    # Act
    result = run_agent_loop(conversation, provider, "fake-model", registry, ctx)

    # Assert
    self.assertEqual(result.response_text, "done")
    self.assertEqual(provider.requests[1]["conversation"].messages[-1].tool_results[0].tool_call_id, "t1")
```

## Test Coverage

### Current Coverage

- Coverage changes as features evolve
- Use the commands below to generate up-to-date local reports
- Prefer focusing on critical paths rather than preserving a stale percentage in docs

### Coverage Goals

- Minimum: 80%
- Target: 90%+
- Critical paths: 100%

### Check Coverage

```bash
# Generate coverage report
python -m pytest tests/ --cov=src --cov-report=term-missing

# View missing lines
python -m pytest tests/ --cov=src --cov-report=term-missing | grep "TOTAL"
```

## Continuous Integration

Tests run automatically on:

- Pull requests
- Commits to main branch
- Releases

### CI Configuration

Tests are configured in `.github/workflows/` (if exists):

```yaml
- name: Run tests
  run: python -m pytest tests/ -q --cov=src
```

## Test Data

### Fixtures

Common test data is stored in fixtures:

```python
# In test file
def setUp(self):
    """Set up test fixtures."""
    self.temp_dir = tempfile.mkdtemp()
    self.config_dir = Path(self.temp_dir) / ".clyde"
    self.config_dir.mkdir(parents=True, exist_ok=True)
```

### Test Sessions

Test sessions are created in temporary directories and cleaned up after tests.

## Troubleshooting

### Common Issues

1. **Import errors**: Ensure `src/` is in Python path
   ```bash
   export PYTHONPATH="${PYTHONPATH}:$(pwd)"
   ```

2. **API key errors**: Tests should use mocks, not real API keys

3. **Permission errors**: Check file permissions in test directories

4. **Slow tests**: Check for network calls (should be mocked)

### Debug Tests

```bash
# Run with verbose output
python -m pytest tests/ -v -s

# Run with pdb debugger
python -m pytest tests/ --pdb

# Run specific failing test with output
python -m pytest tests/test_config.py::TestClassName::test_name -v -s
```

## Performance Tests

```bash
# Run performance benchmarks
python -m pytest tests/ --benchmark-only
```

## Security Tests

- API keys are never logged
- Saved keys live in `~/.clyde/keys.json` with mode 0600
- Secrets are not in git
- `.env` is in `.gitignore`

## Contributing Tests

When adding new features:

1. **Write tests first** (TDD approach)
2. **Test edge cases**
3. **Document test purpose**
4. **Ensure all tests pass**
5. **Check coverage**

## Test Maintenance

- Review and update tests when:
  - Adding new features
  - Fixing bugs
  - Refactoring code
  - Updating dependencies

## Summary

Good testing practices ensure:

- Code reliability
- Regression prevention
- Documentation of behavior
- Confidence in refactoring
- Better code design

**Run tests before every commit!**

```bash
source .venv/bin/activate
python -m pytest tests/ -q
```

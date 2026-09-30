# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Stdlib-only provider layer (no vendor SDKs): Anthropic, OpenAI, Google Gemini, OpenRouter,
  DeepSeek, Mistral, NVIDIA, Cerebras, GLM, MiniMax, Ollama (local, native `/api/chat`) and
  Ollama Cloud
- `provider:model` selection: `clyde --model`, `/model`, `/models`, `clyde --list-models`
- Live model lists from each provider's API, cached for 60s
- `/think off|low|medium|high|on|default` reasoning control, with streamed reasoning shown dimmed
- Retries with backoff on 429/5xx/connection errors, and one-line readable provider errors
- `clyde logout <provider>`; Ollama login suggests tool-capable models that fit your RAM
- Initial context injection pipeline for workspace snapshot, git status, and `CLAUDE.md`
- Tests covering the new context system integration

### Changed
- API keys moved from base64 entries in `config.json` to `~/.clyde/keys.json` (mode 600), with
  shell env vars taking precedence; old configs migrate automatically on first run
- The agent loop uses one code path for every provider; conversation history (including
  reasoning and tool-call signatures) is re-expressed per provider on each request
- Compaction no longer calls a nonexistent `chat_async`, and its summary context never starts on
  an orphaned tool result
- Requires Python 3.14
- Skill frontmatter parsing now supports inline list syntax such as `arguments: [path]`
- README and contributor docs now prefer `uv`-based setup instructions
- Documentation now distinguishes provider-level streaming interfaces from the current turn-based CLI output

## [0.1.0] - 2026-04-01

### Added

#### Core Features
- Multi-provider support for Anthropic, OpenAI, and GLM (Zhipu AI)
- Interactive REPL with prompt-toolkit integration
- Rich interactive terminal output
- Session persistence and management
- Configuration management with basic API key obfuscation

#### CLI Commands
- `clyde` - Start the interactive REPL
- `clyde login` - Interactive API key configuration
- `clyde config` - View current configuration
- `clyde --version` - Show version information

#### Provider Implementations
- **Anthropic Provider**: Claude integration with chat + streaming interfaces
- **OpenAI Provider**: GPT integration with chat + streaming interfaces
- **GLM Provider**: GLM integration with chat + streaming interfaces

#### REPL Features
- Command history with persistent storage
- Auto-suggestions from history
- Slash commands: `/help`, `/exit`, `/clear`, `/save`, `/load`, `/multiline`
- Skill slash commands backed by `SKILL.md`
- Syntax highlighting with Rich library
- Tab completion and multi-line input support

#### Configuration System
- JSON-based configuration storage
- Base64-encoded API keys for basic obfuscation
- Provider-specific settings (API key, base URL, default model)
- Session auto-save option

#### Session Management
- Unique session ID generation
- Conversation history tracking
- Session save/load functionality
- Conversation clear operation

#### Code Quality
- Type hints for all public functions
- Abstract base class for provider implementations
- Data classes for structured data (ChatMessage, ChatResponse)
- Error handling and validation

#### Testing
- Unit tests for core components
- Integration tests for providers
- End-to-end tests for REPL functionality
- Test coverage for configuration management

### Technical Details

#### Architecture
- Modular provider system with base abstraction
- Conversation management with message history
- Configuration management layer
- REPL engine with prompt-toolkit

#### Dependencies
- `anthropic>=0.18.0` - Anthropic SDK
- `openai>=1.0.0` - OpenAI SDK
- `zhipuai>=2.0.0` - Zhipu AI SDK
- `prompt-toolkit>=3.0.0` - Interactive REPL
- `rich>=13.0.0` - Terminal formatting
- `python-dotenv>=1.0.0` - Environment variables

#### File Structure
```
src/
├── providers/          # LLM provider implementations
│   ├── base.py        # Abstract base class
│   ├── anthropic_provider.py
│   ├── openai_provider.py
│   └── glm_provider.py
├── repl/              # Interactive REPL
│   └── core.py
├── agent/             # Session management
│   ├── session.py
│   └── conversation.py
├── config.py          # Configuration management
└── cli.py             # CLI commands
```

### Known Limitations

- Context building is still in early MVP form and needs deeper project summarization
- Permission enforcement exists as a framework but is not fully integrated everywhere
- `/resume`, `/compact`, and `/doctor` are not implemented yet
- The current CLI uses turn-based output even though providers expose streaming interfaces

### Migration Notes

This is the initial MVP release. No migration needed.

### Future Roadmap

- [ ] Context enrichment and project-memory improvements
- [ ] Full permission integration
- [ ] `/resume`, `/compact`, `/doctor`
- [ ] Token usage and cost tracking
- [ ] MCP and plugin-system enhancements

---

## Release Notes

### v0.1.0 - MVP Release

This is the first public release of ClydeCLI, a complete reimplementation of Claude Code. This MVP includes:

- Full multi-provider support
- Interactive REPL
- Session management
- Configuration system
- Tool system and agent loop foundations
- Type-safe implementation

The focus was on building a solid foundation with clean architecture, comprehensive testing, and good developer experience. All core features are working and tested.

**Special Thanks**: This project is inspired by Claude Code and aims to provide an open-source alternative for learning and experimentation.

---

[0.1.0]: https://github.com/dea6cat/ClydeCLI/releases/tag/v0.1.0

# Project structure

[Back to the README](../README.md)

```text
ClydeCLI/
├── src/
│   ├── cli.py              # CLI entry
│   ├── config.py           # config.json and default model
│   ├── agent/              # conversation, sessions, agent loop, cost tracking
│   ├── providers/          # LLM providers, the model catalog, cardShuffle, Laya, local model sources and fit
│   ├── repl/               # Interactive REPL
│   ├── command_system/     # slash commands (/doctor, /cost, /context, ...)
│   ├── context_system/     # workspace, git, README and CLYDE.md memory context; token estimation
│   ├── compact_service/    # /compact and auto-compaction
│   ├── output_styles/      # reply style prompts
│   ├── skills/             # SKILL.md loading and creation
│   ├── plugins.py          # plugin install and loading
│   ├── startup/            # setup report
│   └── tool_system/        # tool registry, permissions, validation, tools/
├── tests/                  # mirrors src/
├── .clyde/
│   └── skills/             # Project-local custom skills
└── FEATURE_LIST.md         # Current feature status
```

# Security

ClydeCLI runs commands and edits files on your machine on a model's behalf, so how it handles permissions and secrets matters.

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private reporting: the repository's **Security** tab, then **Report a vulnerability**
(<https://github.com/dea6cat/ClydeCLI/security/advisories/new>). Only the maintainer sees it.

Include what you found, how to reproduce it, the version (`clyde --version`) and what an attacker would gain.

There is one maintainer and no team, so there is no response-time guarantee; reports are read and answered as soon as possible. Fixes go into
the next release, and the newest release is the only one that gets them.

## What counts

- Getting past a permission prompt or a `deny` rule (Bash, Edit, Write, WebFetch, WebSearch, MCP tools).
- Escaping the sandbox (`sandbox-exec` on macOS, `bwrap` on Linux).
- Making Clyde send file contents, keys or prompts anywhere other than the model provider you chose. [EGRESS.md](EGRESS.md) lists every
  destination; one it does not list is a bug.
- A skill, plugin or MCP server getting past SkillSpector's `DO_NOT_INSTALL` hold-back.
- Secrets (key files, `.env`) reaching the model without the confirmation they require.

## What does not

- A model doing something harmful that you approved at a prompt.
- Weaknesses in a dependency that Clyde does not use unsafely: report those to that project.
- Anything that needs you to have already run hostile code as yourself.

## Known limits

Stated in the open so you do not have to find them: `/rewind` does not undo changes made by shell commands, and the macOS sandbox is built on
`sandbox-exec`, which Apple has deprecated. A failed SkillSpector scan loads the item with a warning unless you set `CLYDE_SKILL_SCAN=closed`.

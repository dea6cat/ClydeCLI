# Licence

[Back to the README](../README.md)

Source-available, not open source: free for noncommercial use under the
[PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0); commercial use needs
written permission. Copies obtained before this change remain MIT. See [LICENSE](../LICENSE).

**Acceptance.** The first time you run `clyde` (a new install, or an older install after updating) it shows the terms and asks
you to type `I accept`; Enter alone, anything else, or Ctrl+C declines, nothing is saved, and Clyde exits with status 3. The
answer is saved in `~/.clyde/license.json`, so it asks once per machine, and again only if the terms change. Installing cannot
ask (`uv tool install` runs no prompts), so the first run is where you accept.

| Command | What it does |
|---|---|
| `clyde license` | Show the terms and whether this machine accepted them |
| `clyde license accept` | Accept (typed phrase) without starting the app |
| `CLYDE_ACCEPT_LICENSE=1 clyde -p "..."` | For scripts, CI and editors with no terminal: accepts for that run and saves nothing |
| `CLYDE_ACCEPT_LICENSE=1 clyde license accept` | The same, but saves the acceptance on that machine |

`clyde --version`, `clyde license`, `clyde doctor`, `clyde update` and `clyde uninstall` work without accepting (so you can leave). This is a click-through record, not copy protection: the
licence is what binds, and the check can be removed from the source by anyone who has it.

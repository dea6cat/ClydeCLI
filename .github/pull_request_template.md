## What this changes, and why

<!-- One thing per pull request. Link the issue it closes, if there is one. -->

## How you can tell it works

<!-- The test you added or changed, or the command you ran and what it printed. A fix should come with a test that fails without it. -->

## Checklist

- [ ] `python -m unittest discover -s tests -t . -q` passes
- [ ] Behavior changes have a test
- [ ] User-visible changes have a line under `[Unreleased]` in `CHANGELOG.md`
- [ ] If it touches the network, `EGRESS.md` says so (a test fails if the code names a host that file does not)
- [ ] I read [GOVERNANCE.md](../GOVERNANCE.md): changes to behavior, permissions, privacy or the licence were discussed in an issue first

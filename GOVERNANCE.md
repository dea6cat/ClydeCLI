# Governance

How decisions get made in ClydeCLI, and how that can grow beyond one person. Short on purpose: it describes what is true today.

## Who decides

ClydeCLI has **one maintainer**, [@dea6cat](https://github.com/dea6cat), who has the final say on what is merged and released. There is no
committee and no company behind it. This document exists so that can change: see [Becoming a maintainer](#becoming-a-maintainer).

For anything that changes what Clyde does to a user (behavior, permissions, privacy, what leaves the machine, the licence), open an issue or a
discussion **before** writing the code, so you do not spend a week on something that will be declined. Small fixes, tests and docs can go
straight to a pull request.

## What a good change looks like

- **One thing per pull request**, with a description of what changed and why.
- **A test for behavior.** A fix comes with a test that fails without it; a claim about performance or size comes with the measurement.
- **CI green.** Two checks run on every push: the full test suite on Python 3.12, 3.13 and 3.14 (`python -m unittest discover -s tests -t . -q`),
  and Pylint (score 9 or higher). Run the tests before you push.
- **Docs follow behavior.** User-visible changes get a line under `[Unreleased]` in [CHANGELOG.md](CHANGELOG.md). Anything that touches the
  network also updates [EGRESS.md](EGRESS.md); a test fails if the code names a host that document does not.
- The practical details (setup, style, how to run things) are in [CONTRIBUTING.md](CONTRIBUTING.md).

## Releases

Releases are cut from `main` with `scripts/release.sh X.Y.Z` once CI is green: it bumps the version, turns `[Unreleased]` into the release,
tags it and pushes. There is **no fixed schedule**; a release happens when a set of changes is ready. `clyde update` follows either `latest`
(every commit on `main`) or `stable` (tagged releases).

## Licence and contributions

ClydeCLI is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE). There is no contributor licence agreement. Under
GitHub's Terms of Service, a contribution to a repository that carries a licence is licensed under that same licence unless you and the
maintainer agree otherwise in writing, so a pull request here is under the PolyForm Noncommercial terms. If that is a problem for you, ask
before you contribute.

## Disagreements

Discuss it in the issue or pull request. If the maintainer and you still disagree, the maintainer decides. You are free to fork within the
terms of the licence.

## Security and conduct

- **Security problems**: do not open a public issue. See [SECURITY.md](SECURITY.md).
- **Conduct**: the project follows the [Contributor Covenant 2.0](https://www.contributor-covenant.org/version/2/0/code_of_conduct/).
  Report unacceptable behavior privately to the maintainer, at the address listed as the author in `pyproject.toml`.

## Becoming a maintainer

A maintainer can review and merge pull requests (write access). It is offered to people who have shown, over time, that they work the way this
document describes: several merged contributions, reviews that caught real problems, and patience with the details above. There is no formal
count. The current maintainer invites; if you would like to be considered, say so in a discussion. A second maintainer is the goal, because one
person is a single point of failure for the project.

## Changing this document

By pull request, like anything else. It describes the project; if the project changes, this should too.

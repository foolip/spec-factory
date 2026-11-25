This repository enables repositories of WHATWG standards to be organized centrally to a certain extent. This is useful for the support files (the files with the `.template` and `.template-part` extensions), which are often nearly identical and prone to errors.

`factory.py` takes care of updating existing WHATWG standard repositories. It assumes they are in parallel directories using their "shortname" as directory name. `factory.json` supplies data for a exceptional cases.

## Repository settings

`factory.py --check-settings --all` checks the GitHub settings of the standards' repositories, and `factory.py --update-settings --all` fixes them (both also work with `--single <shortname> <h1>` instead of `--all`). They need `gh`, logged in as someone with admin access for `--update-settings`, and exit with status 1 if a problem remains. Currently checked:

- In the organization:
  - A custom property `standard` (true/false) exists.
  - An organization ruleset `standards` exists, as defined in `factory.py`: on the default branch of every repository whose `standard` property is true, no deletion, no force pushes, linear history, a pull request with 1 approval, the `Build` and `Participation` checks passing, and no bypass. Reading it needs an organization owner; otherwise `--check-settings` skips it.
- In each standard's repository:
  - `whatbot` has write access, which it needs to report the Participation check.
  - Its `standard` property is true, so that the ruleset applies. This is only set once the default branch reports both required checks, as otherwise no pull request could be merged.
  - The ruleset's rules are in effect on the default branch (anyone with read access can check this).
  - The default branch has no classic branch protection left, which the ruleset replaces. Reading this needs admin access; otherwise it's skipped.

A new standard is covered by running `--update-settings` for it.

To see how all the organization's repositories are protected today (classic branch protection, rulesets and the rules in effect), grouped by identical protection of the default branch, run `./branch-protection-report.py` (`--json` for the raw data, `--include-archived` to include archived repositories). Reading classic protection needs admin access.

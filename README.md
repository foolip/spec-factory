This repository enables repositories of WHATWG standards to be organized centrally to a certain extent. This is useful for the support files (the files with the `.template` and `.template-part` extensions), which are often nearly identical and prone to errors.

`factory.py` takes care of updating existing WHATWG standard repositories. It assumes they are in parallel directories using their "shortname" as directory name. `factory.json` supplies data for a exceptional cases.

## Repository settings

`factory.py --check-settings --all` checks the GitHub settings of the standards' repositories, and `factory.py --update-settings --all` fixes them (both also work with `--single <shortname> <h1>` instead of `--all`). They need `gh`, logged in as someone with admin access for `--update-settings`, and exit with status 1 if a problem remains. In each standard's repository:

- `whatbot` has write access, which it needs to report the Participation check.
- The default branch is protected by these repository rulesets, as defined in `factory.py`, and no other rulesets named `standard` or `standard: …` exist:
  - `standard`: no deletion, no force pushes, linear history, a pull request, and the `Build` and `Participation` checks passing. Nobody can bypass it. It's only created once the default branch reports the required checks, as otherwise no pull request could be merged.
  - `standard: approval`: 1 approving review, which the standard's workstream editors and authors (per whatwg/sg's `db.json`) can bypass on pull requests: they can merge their own pull requests, but not push directly or skip the checks. (A bypass applies to every rule in its ruleset, which is why this is separate.) Their GitHub accounts come from the `github` field in `db.json`; anyone without one is reported, and the repository is left unchanged.
  - `standard: push restriction`: only if `push_teams` or `push_users` is set, see below.
- `"settings"` in `factory.json` adjusts these per standard:
  - `"extra_required_checks": ["Test"]`: checks required in addition to `Build` and `Participation`.
  - `"require_up_to_date": true`: branches must be up to date with the default branch before merging.
  - `"push_teams": ["editors-all-specs"]`, `"push_users": ["miketaylr"]`: only these teams and people can push or merge to the default branch.
- The default branch has no classic branch protection left, which the rulesets replace. It's only deleted once all the rules above are in effect. Reading it needs admin access; otherwise it's skipped.

A new standard is covered by running `--update-settings` for it.

To see how all the organization's repositories are protected today (organization rulesets, and per repository its classic branch protection, its own rulesets whether active or not, and the rules in effect), grouped by identical protection of the default branch, run `./branch-protection-report.py` (`--json` for the raw data, `--include-archived` to include archived repositories). Reading classic protection needs admin access.

To see who can write to each repository (directly, through teams, or as an organization owner), and which repositories fewer than two people can write to, run `./access-report.py` (`--min`, `--bots` and `--json` adjust it). It needs admin access to the repositories and `gh` with the `read:org` scope.

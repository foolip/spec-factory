This repository enables repositories of WHATWG standards to be organized centrally to a certain extent. This is useful for the support files (the files with the `.template` and `.template-part` extensions), which are often nearly identical and prone to errors.

`factory.py` takes care of updating existing WHATWG standard repositories. It assumes they are in parallel directories using their "shortname" as directory name. `factory.json` supplies data for a exceptional cases.

## Repository settings

`factory.py --check-settings --all` checks the GitHub settings of the standards' repositories, and `factory.py --update-settings --all` fixes them (both also work with `--single <shortname> <h1>` instead of `--all`). They need `gh`, logged in as someone with admin access for `--update-settings`, and exit with status 1 if a problem remains. Currently checked:

- `whatbot` has write access, which it needs to report the Participation check.

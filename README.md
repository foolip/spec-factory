This repository enables repositories of WHATWG standards to be organized centrally to a certain extent. This is useful for the support files (the files with the `.template` and `.template-part` extensions), which are often nearly identical and prone to errors.

`factory.py` takes care of updating existing WHATWG standard repositories. It assumes they are in parallel directories using their "shortname" as directory name. `factory.json` supplies data for a exceptional cases.

## Repository settings

`factory.py --settings --all` (or `--settings --single <shortname> <h1>`) checks and fixes the GitHub settings of the standards' repositories, instead of their files. It needs `gh` logged in as someone with admin access. For each standard it:

- gives `whatbot` write access, which it needs to report the Participation check;
- checks that `main` has a ruleset requiring pull requests, and stops there if not;
- creates or updates the `production` environment so that only the `main` branch can use it;
- sets the environment's R2 deploy secrets (`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT`) to the values in `cloudflare-r2.json` in the private whatwg/admin repository, or to environment variables of the same names if all three are set.

To rotate the credentials, create a new R2 token, update `cloudflare-r2.json`, run `factory.py --settings --all`, and delete the old token. It exits with status 1 if anything needs a person. See [whatwg/misc-server#107](https://github.com/whatwg/misc-server/issues/107).

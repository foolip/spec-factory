#!/usr/bin/env python

import argparse, os, subprocess, uuid, json, requests

OBSOLETE_FILES = [".travis.yml", "deploy_key.enc", "CONTRIBUTING.md", "PULL_REQUEST_TEMPLATE.md"]
TEMPLATES = {}
TEMPLATE_PARTS = {}
DB = json.loads(requests.get("https://github.com/whatwg/sg/raw/main/db.json").text)
FACTORY_DB = {}

def read_file(file):
    return open(file, "r", encoding="utf-8", newline="\n").read()

def write_file(file, contents):
    dirs = os.path.dirname(file)
    if dirs:
        os.makedirs(dirs, exist_ok=True)
    open(file, "w", encoding="utf-8", newline="\n").write(contents)

def href_to_shortname(href):
    return href[len("https://"):href.index(".")]

def find_files_with_extension(extension, recurse=True):
    paths = []
    for root, dirs, files in os.walk("."):
        for file in files:
            if file.endswith(extension):
                path = os.path.relpath(os.path.join(root, file), start=".")
                paths.append(path)
        if not recurse:
            del dirs[:]
    return paths


def gather_files(extension):
    files = {}
    for path in find_files_with_extension(extension):
        files[path] = read_file(path)
    return files


def copy_and_fill_templates(variables):
    output = {}
    for template in TEMPLATES:
        output_name = template[:-len(".template")]
        output_contents = TEMPLATES[template]
        if output_name == "README.md":
            if variables["readme"]:
                output_contents += "\n" + TEMPLATE_PARTS[variables["readme"]]
            if os.path.isfile("READMEEND.md"):
                output_contents += "\n" + read_file("READMEEND.md")
        output[output_name] = fill_template(output_contents, variables)
    return output

def fill_template(contents, variables):
    for variable, data in variables.items():
        if variable in ("not_these_templates", "readme", "settings"):
            continue
        elif variable == "extra_files" and data != "":
            data = "\n\tEXTRA_FILES=\"{}\" \\".format(data)
        elif variable == "bikeshed_indent_size":
            data = str(data)
        elif variable == "bikeshed_max_line_length" and data != "":
            data = "\nmax_line_length = {}".format(data)
        elif variable == "build_with_node" and data != "":
            data = """
    - uses: actions/setup-node@v4
      with:
        node-version: 20
    - run: npm install"""
        elif variable == "post_build_step" and data != "":
            data = "\n\tPOST_BUILD_STEP='{}' \\".format(data)
        elif variable == ".gitignore":
            output = ""
            for entry in data:
                output += "\n{}".format(entry)
            data = output
        elif variable == "extra_implementers":
            output = ""
            for entry in data:
                output += "\n   * {}: …".format(entry)
            data = output
        elif variable == "a11y-check":
            output = ""
            if data:
                output = "\n- [ ] Corresponding [HTML AAM](https://w3c.github.io/html-aam/) & [ARIA in HTML](https://w3c.github.io/html-aria/) issues & PRs:"
            data = output
        contents = contents.replace("@@{}@@".format(variable), data)
    return contents


def update_files(shortname, name, in_main=False):
    os.chdir("../{}".format(shortname))

    variables = {
        "source": "source",
        "shortname": shortname,
        "h1": name,
        "extra_files": "",
        "bikeshed_indent_size": 1,
        "bikeshed_max_line_length": "",
        "build_with_node": "",
        "post_build_step": "",
        ".gitignore": [],
        "not_these_templates": None,
        "extra_implementers": [],
        "a11y-check": False,
        "readme": None
    }
    if shortname in FACTORY_DB:
        variables.update(FACTORY_DB[shortname])


    # HTML does not use Bikeshed (yet). We do want some output for comparison purposes
    if variables["shortname"] != "html":
        [bs_file] = find_files_with_extension(".bs", recurse=False)
        bs = bs_file[:-len(".bs")]
        variables["bs"] = bs
        variables["source"] = bs + ".bs"

    files = copy_and_fill_templates(variables)

    if in_main:
        subprocess.run(["git", "checkout", "main"], capture_output=True)
        subprocess.run(["git", "pull"], capture_output=True)

    for file in files:
        if variables["not_these_templates"] and file in variables["not_these_templates"]:
            continue
        write_file(file, files[file])
    for file in OBSOLETE_FILES:
        if os.path.isfile(file):
            os.remove(file)

    os.chdir(".")


def create_pr(shortname):
    os.chdir("../{}".format(shortname))

    subprocess.run(["git", "add", "-A"], capture_output=True)
    if b"Changes to be committed" in subprocess.run(["git", "status"], capture_output=True).stdout:
        branch = "meta-template/{}".format(uuid.uuid1())
        subprocess.run(["git", "checkout", "-b", branch], capture_output=True)
        subprocess.run(["git", "commit", "-m", "Meta: update repository files\n\nSee https://github.com/whatwg/spec-factory for details."], capture_output=True)
        subprocess.run(["git", "push", "-u", "origin", branch], capture_output=True)
        subprocess.run(["gh", "pr", "create", "-f"])

    os.chdir(".")


# Repository settings on GitHub, checked by --check-settings and fixed by
# --update-settings. Organization-level settings are checked once, then each
# repository's. Each check takes whether to fix it (and the repository) and
# returns a list of problems that remain.

ORG = "whatwg"
BOT = "whatbot"

# Branch protection is an organization ruleset that applies to the default
# branch of every repository whose custom property "standard" is true.
PROPERTY = "standard"
REQUIRED_CHECKS = ["Build", "Participation"]


def pull_request_rule(approvals):
    return {"type": "pull_request", "parameters": {
        "required_approving_review_count": approvals,
        "dismiss_stale_reviews_on_push": False,
        "require_code_owner_review": False,
        "require_last_push_approval": False,
        "required_review_thread_resolution": False,
    }}


# The organization ruleset requires pull requests but no approval; nobody can
# bypass it. Each standard's "standard: approval" repository ruleset then
# requires 1 approval, which the standard's editors and authors may bypass on
# pull requests (see desired_repo_rulesets).
RULES = [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {"type": "required_linear_history"},
    pull_request_rule(0),
    {"type": "required_status_checks", "parameters": {
        "strict_required_status_checks_policy": False,
        "required_status_checks": [{"context": check} for check in REQUIRED_CHECKS],
    }},
]
RULESET = {
    "name": "standards",
    "target": "branch",
    "enforcement": "active",
    "bypass_actors": [],
    "conditions": {
        "ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []},
        "repository_property": {
            "include": [{"name": PROPERTY, "property_values": ["true"], "source": "custom"}],
            "exclude": [],
        },
    },
    "rules": RULES,
}
PROPERTY_SCHEMA = {
    "value_type": "true_false",
    "required": False,
    "description": "A WHATWG standard: its default branch is protected by the standards ruleset (see whatwg/spec-factory)",
}


def gh_api(*args, input=None, allow_404=False):
    """Runs `gh api`; with allow_404, returns None for a 404."""
    command = ["gh", "api", *args]
    if input is not None:
        command += ["--input", "-"]
        input = json.dumps(input)
    result = subprocess.run(command, input=input, capture_output=True, text=True)
    if result.returncode != 0:
        # GitHub answers 404 when the token lacks a scope, so that isn't
        # "doesn't exist".
        if "admin:org" in result.stderr:
            raise RuntimeError("gh needs the admin:org scope: gh auth refresh -h github.com -s admin:org")
        if allow_404 and "HTTP 404" in result.stderr:
            return None
        raise RuntimeError("gh api {}: {}".format(" ".join(args), result.stderr.strip()))
    return result.stdout


def gh_json(*args, **kwargs):
    output = gh_api(*args, **kwargs)
    return None if output is None else json.loads(output)


def contains(expected, actual):
    """Whether everything in `expected` is also in `actual`. GitHub adds
    fields with default values, so an exact comparison would fail."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and contains(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(expected) == len(actual) and all(
            any(contains(e, a) for a in actual) for e in expected)
    return expected == actual


def check_property_schema(update):
    if gh_json("orgs/{}/properties/schema/{}".format(ORG, PROPERTY), allow_404=True) is not None:
        return []
    if not update:
        return ["no custom property {!r}".format(PROPERTY)]
    gh_api("-X", "PUT", "orgs/{}/properties/schema/{}".format(ORG, PROPERTY), input=PROPERTY_SCHEMA)
    print("  fixed: created the custom property {!r}".format(PROPERTY))
    return []


def check_org_ruleset(update):
    try:
        rulesets = gh_json("orgs/{}/rulesets".format(ORG))
    except RuntimeError as e:
        # Reading organization rulesets needs an organization owner. Without
        # that, the per-repository check of the rules in effect still runs.
        if update or not any(x in str(e) for x in ("HTTP 403", "HTTP 404", "admin:org")):
            raise
        print("  not checked: organization ruleset (needs an organization owner, and gh with the admin:org scope)")
        return []
    ids = [r["id"] for r in rulesets if r["name"] == RULESET["name"]]
    if not ids:
        if not update:
            return ["no organization ruleset {!r}".format(RULESET["name"])]
        gh_api("-X", "POST", "orgs/{}/rulesets".format(ORG), input=RULESET)
        print("  fixed: created the organization ruleset {!r}".format(RULESET["name"]))
        return []
    current = gh_json("orgs/{}/rulesets/{}".format(ORG, ids[0]))
    if contains(RULESET, current):
        return []
    if not update:
        return ["organization ruleset {!r} differs from factory.py".format(RULESET["name"])]
    gh_api("-X", "PUT", "orgs/{}/rulesets/{}".format(ORG, ids[0]), input=RULESET)
    print("  fixed: updated the organization ruleset {!r}".format(RULESET["name"]))
    return []


ORG_CHECKS = [check_property_schema, check_org_ruleset]


def check_bot_access(update, repo):
    """whatbot reports the Participation check (a commit status), which needs
    write access."""
    permission = gh_api("repos/{}/collaborators/{}/permission".format(repo, BOT), "--jq", ".permission").strip()
    if permission in ("admin", "write"):
        return []
    if update:
        gh_api("-X", "PUT", "repos/{}/collaborators/{}".format(repo, BOT), "-f", "permission=push")
        print("  fixed: gave {} write access (was {})".format(BOT, permission))
        return []
    return ["{} has {} access, needs write".format(BOT, permission)]


def reported_checks(repo, ref):
    runs = gh_api("repos/{}/commits/{}/check-runs".format(repo, ref), "--paginate", "--jq", ".check_runs[].name")
    statuses = gh_api("repos/{}/commits/{}/status".format(repo, ref), "--jq", ".statuses[].context")
    return set(runs.split("\n") + statuses.split("\n")) - {""}


# Per-repository additions to the organization ruleset, from "settings" in
# factory.json, each applied as a repository ruleset (rulesets combine, so
# these can only add restrictions):
#   "extra_required_checks": ["Test"]   checks required on top of REQUIRED_CHECKS
#   "require_up_to_date": true          branches must be up to date before merging
#   "push_teams": ["editors-all-specs"] only these teams (and push_users) can
#   "push_users": ["miketaylr"]         push or merge to the default branch
# Every standard also gets "standard: approval" (see above).
EXTRA_RULESET_PREFIX = "standard: "

# GitHub accounts of the people in whatwg/sg's db.json, which only has their
# names and emails: {"email": "login"}.
GITHUB_USERS_FILE = "github-users.json"


def github_users():
    return json.loads(read_file(GITHUB_USERS_FILE))


def editors_and_authors(shortname):
    """The workstream editors and the authors of a standard, per db.json, as
    (name, email) pairs."""
    for workstream in DB["workstreams"]:
        for standard in workstream["standards"]:
            if href_to_shortname(standard["href"]) == shortname:
                people = workstream["editors"] + standard.get("authors", [])
                return sorted({(p["name"], p["email"]) for p in people})
    raise RuntimeError("{} isn't in db.json".format(shortname))


USER_IDS = {}


def user_id(login):
    if login not in USER_IDS:
        USER_IDS[login] = gh_json("users/{}".format(login))["id"]
    return USER_IDS[login]


def repo_settings(repo):
    return FACTORY_DB.get(repo.split("/")[1], {}).get("settings", {})


def team_id(slug):
    return gh_json("orgs/{}/teams/{}".format(ORG, slug))["id"]


def desired_repo_rulesets(repo):
    """The repository rulesets that factory.json asks for, by name."""
    settings = repo_settings(repo)
    unknown = set(settings) - {"extra_required_checks", "require_up_to_date", "push_teams", "push_users"}
    if unknown:
        raise RuntimeError("unknown settings in factory.json: {}".format(", ".join(sorted(unknown))))
    branch = {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}}
    rulesets = {}

    # 1 approval, except for the editors and authors, who may merge their own
    # pull requests ("pull_request" bypass mode: they still can't push
    # directly, and the organization ruleset still applies to them).
    logins = github_users()
    people = editors_and_authors(repo.split("/")[1])
    unmapped = ["{} <{}>".format(name, email) for name, email in people if email not in logins]
    if unmapped:
        raise RuntimeError("no GitHub account in {} for: {}".format(GITHUB_USERS_FILE, ", ".join(unmapped)))
    name = EXTRA_RULESET_PREFIX + "approval"
    rulesets[name] = {
        "name": name, "target": "branch", "enforcement": "active",
        "bypass_actors": [{"actor_type": "User", "actor_id": user_id(login), "bypass_mode": "pull_request"}
                          for login in sorted({logins[email] for _, email in people})],
        "conditions": branch,
        "rules": [pull_request_rule(1)],
    }
    up_to_date = settings.get("require_up_to_date", False)
    checks = list(settings.get("extra_required_checks", []))
    if up_to_date:
        # "Up to date" is a property of a set of required checks, so this
        # ruleset requires all of them, strictly.
        checks = REQUIRED_CHECKS + [c for c in checks if c not in REQUIRED_CHECKS]
    if checks:
        name = EXTRA_RULESET_PREFIX + "required checks"
        rulesets[name] = {
            "name": name, "target": "branch", "enforcement": "active", "bypass_actors": [],
            "conditions": branch,
            "rules": [{"type": "required_status_checks", "parameters": {
                "strict_required_status_checks_policy": up_to_date,
                "required_status_checks": [{"context": c} for c in checks],
            }}],
        }
    if settings.get("push_teams") or settings.get("push_users"):
        name = EXTRA_RULESET_PREFIX + "push restriction"
        rulesets[name] = {
            "name": name, "target": "branch", "enforcement": "active",
            # Only the bypass actors may update the branch, which includes
            # merging pull requests.
            "bypass_actors": [{"actor_type": "Team", "actor_id": team_id(t), "bypass_mode": "always"}
                              for t in settings.get("push_teams", [])] +
                             [{"actor_type": "User", "actor_id": user_id(u), "bypass_mode": "always"}
                              for u in settings.get("push_users", [])],
            "conditions": branch,
            "rules": [{"type": "update"}],
        }
    return rulesets


def check_repo_rulesets(update, repo):
    """The repository rulesets from factory.json exist and match; other
    rulesets that factory.py manages (by name) are removed."""
    problems = []
    desired = desired_repo_rulesets(repo)
    existing = {r["name"]: r["id"] for r in gh_json("repos/{}/rulesets".format(repo))
                if r.get("source_type") == "Repository" and r["name"].startswith(EXTRA_RULESET_PREFIX)}
    for name, ruleset in desired.items():
        if name not in existing:
            if not update:
                problems.append("no repository ruleset {!r}".format(name))
                continue
            gh_api("-X", "POST", "repos/{}/rulesets".format(repo), input=ruleset)
            print("  fixed: created the repository ruleset {!r}".format(name))
        elif not contains(ruleset, gh_json("repos/{}/rulesets/{}".format(repo, existing[name]))):
            if not update:
                problems.append("repository ruleset {!r} differs from factory.json".format(name))
                continue
            gh_api("-X", "PUT", "repos/{}/rulesets/{}".format(repo, existing[name]), input=ruleset)
            print("  fixed: updated the repository ruleset {!r}".format(name))
    for name in set(existing) - set(desired):
        if not update:
            problems.append("repository ruleset {!r} isn't in factory.json".format(name))
            continue
        gh_api("-X", "DELETE", "repos/{}/rulesets/{}".format(repo, existing[name]))
        print("  fixed: deleted the repository ruleset {!r}".format(name))
    return problems


def check_branch_protection(update, repo):
    """The default branch is protected by the organization ruleset (through
    the custom property), and no longer by classic branch protection."""
    problems = []
    branch = gh_api("repos/{}".format(repo), "--jq", ".default_branch").strip()
    # Fails (e.g. an editor without a GitHub account in github-users.json)
    # before anything is changed.
    repo_rulesets = desired_repo_rulesets(repo)

    values = gh_json("repos/{}/properties/values".format(repo))
    if not any(v["property_name"] == PROPERTY and v["value"] == "true" for v in values):
        # Setting the property makes the ruleset require the checks, so only
        # do that once the branch reports them; otherwise no PR could merge.
        missing = [c for c in REQUIRED_CHECKS if c not in reported_checks(repo, branch)]
        if missing:
            return ["{} doesn't report {}, so not setting {!r}".format(branch, ", ".join(missing), PROPERTY)]
        if not update:
            return ["custom property {!r} isn't true".format(PROPERTY)]
        gh_api("-X", "PATCH", "orgs/{}/properties/values".format(ORG), input={
            "repository_names": [repo.split("/")[1]],
            "properties": [{"property_name": PROPERTY, "value": "true"}],
        })
        print("  fixed: set {!r} to true".format(PROPERTY))

    # The rules in effect on the branch, from any ruleset. Anyone with read
    # access can see these.
    effective = gh_json("repos/{}/rules/branches/{}".format(repo, branch))
    expected = RULES + [rule for r in repo_rulesets.values() for rule in r["rules"]]
    for rule in expected:
        if not any(contains(rule, r) for r in effective):
            problems.append("rule {} isn't in effect on {}".format(rule["type"], branch))
    if problems:
        return problems

    # Classic branch protection is redundant once the ruleset is in effect.
    # Reading it needs admin access; without it, this part isn't checked.
    try:
        classic = gh_json("repos/{}/branches/{}/protection".format(repo, branch), allow_404=True)
    except RuntimeError:
        classic = None
    if classic is not None:
        if not update:
            return ["{} still has classic branch protection (redundant)".format(branch)]
        gh_api("-X", "DELETE", "repos/{}/branches/{}/protection".format(repo, branch))
        print("  fixed: deleted classic branch protection")
    return problems


# check_repo_rulesets comes before check_branch_protection, so that the
# additions are in effect before classic branch protection is deleted.
REPO_CHECKS = [check_bot_access, check_repo_rulesets, check_branch_protection]


def run_checks(label, checks, update, *args):
    print(label)
    ok = True
    for check in checks:
        try:
            problems = check(update, *args)
        except RuntimeError as e:
            problems = [str(e)]
        for problem in problems:
            print("  problem: {}".format(problem))
        ok = ok and not problems
    return ok


def settings(shortnames, update):
    """Returns whether all settings are (now) correct."""
    ok = run_checks(ORG, ORG_CHECKS, update)
    for shortname in shortnames:
        repo = "{}/{}".format(ORG, shortname)
        ok = run_checks(repo, REPO_CHECKS, update, repo) and ok
    return ok


def all_shortnames():
    return [href_to_shortname(standard["href"])
            for workstream in DB["workstreams"] for standard in workstream["standards"]]


def update_all_standards(create_prs = False):
    for workstream in DB["workstreams"]:
        for standard in workstream["standards"]:
            shortname = href_to_shortname(standard["href"])

            update_files(shortname, standard["name"], True)

            if create_prs:
                 create_pr(shortname)


def main():
    global TEMPLATES, FACTORY_DB, TEMPLATE_PARTS

    TEMPLATES = gather_files(".template")
    FACTORY_DB = json.loads(read_file("factory.json"))
    TEMPLATE_PARTS = gather_files(".template-part")

    parser = argparse.ArgumentParser()
    parser.add_argument("--single", nargs=2, type=str, metavar=("<shortname>", "<h1>"), help="generate a single standard, e.g., --single xhr XMLHttpRequest")
    parser.add_argument("--all", action="store_true", help="generate all standards (as per SG's db.json)")
    parser.add_argument("--create-prs", action="store_true", help="create PRs; can only be used in combination with --all")
    parser.add_argument("--check-settings", action="store_true", help="instead of files, check the GitHub repository settings (needs gh); use with --all or --single")
    parser.add_argument("--update-settings", action="store_true", help="instead of files, fix the GitHub repository settings (needs gh, with admin access); use with --all or --single")
    args = parser.parse_args()

    if args.check_settings or args.update_settings:
        if args.all:
            shortnames = all_shortnames()
        elif args.single:
            shortnames = [args.single[0]]
        else:
            parser.print_help()
            exit(1)
        exit(0 if settings(shortnames, args.update_settings) else 1)

    if args.single and not args.create_prs:
        update_files(args.single[0], args.single[1])
    elif args.all:
        update_all_standards(args.create_prs)
    else:
        parser.print_help()
        exit(1)
    exit(0)

main()

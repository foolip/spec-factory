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
# --update-settings. Each check takes whether to fix it and the repository
# ("whatwg/<shortname>"), and returns a list of problems that remain.

ORG = "whatwg"
BOT = "whatbot"
REQUIRED_CHECKS = ["Build", "Participation"]

# The default branch of each standard is protected by repository rulesets
# whose names end in MANAGED (any others are left alone). A ruleset's bypass
# list applies to all its rules, so they're split up:
#
#   "default ..."           no deletion, no force pushes, linear history, pull
#                           requests, required checks; no bypass
#   "approval ..."          1 approving review, which the standard's editors
#                           (per whatwg/sg's db.json) can bypass on pull
#                           requests: they can merge their own pull requests,
#                           but still not push directly or skip the checks
#
# "settings" in factory.json adjusts these per standard:
#   "extra_required_checks": ["Test"]   checks required besides REQUIRED_CHECKS
#   "require_up_to_date": true          branches must be up to date to merge
MANAGED = " (via spec-factory, do not edit)"
DEFAULT_RULESET = "default" + MANAGED
APPROVAL_RULESET = "approval" + MANAGED
SETTINGS = {"extra_required_checks", "require_up_to_date"}
BRANCH = {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}}


def gh_api(*args, input=None, allow_404=False):
    """Runs `gh api`; with allow_404, returns None for a 404."""
    command = ["gh", "api", *args]
    if input is not None:
        command += ["--input", "-"]
        input = json.dumps(input)
    result = subprocess.run(command, input=input, capture_output=True, text=True)
    if result.returncode != 0:
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


def pull_request_rule(approvals):
    return {"type": "pull_request", "parameters": {
        "required_approving_review_count": approvals,
        "dismiss_stale_reviews_on_push": False,
        "require_code_owner_review": False,
        "require_last_push_approval": False,
        "required_review_thread_resolution": False,
    }}


def editors(shortname):
    """The editors of a standard's workstream, per db.json, as (name, GitHub
    login or None) pairs."""
    for workstream in DB["workstreams"]:
        for standard in workstream["standards"]:
            if href_to_shortname(standard["href"]) == shortname:
                return [(p["name"], p.get("github")) for p in workstream["editors"]]
    raise RuntimeError("{} isn't in db.json".format(shortname))


USER_IDS = {}


def user_id(login):
    if login not in USER_IDS:
        USER_IDS[login] = gh_json("users/{}".format(login))["id"]
    return USER_IDS[login]


def ruleset(name, rules, bypass_actors=()):
    return {"name": name, "target": "branch", "enforcement": "active",
            "bypass_actors": list(bypass_actors), "conditions": BRANCH, "rules": rules}


def desired_rulesets(repo):
    """The rulesets a standard's repository should have, by name. Raises if
    factory.json or db.json is missing something."""
    shortname = repo.split("/")[1]
    settings = FACTORY_DB.get(shortname, {}).get("settings", {})
    unknown = set(settings) - SETTINGS
    if unknown:
        raise RuntimeError("unknown settings in factory.json: {}".format(", ".join(sorted(unknown))))
    people = editors(shortname)
    unmapped = [name for name, login in people if not login]
    if unmapped:
        raise RuntimeError("no \"github\" in whatwg/sg's db.json for: {}".format(", ".join(unmapped)))

    checks = REQUIRED_CHECKS + [c for c in settings.get("extra_required_checks", []) if c not in REQUIRED_CHECKS]
    rulesets = {}
    rulesets[DEFAULT_RULESET] = ruleset(DEFAULT_RULESET, [
        {"type": "deletion"},
        {"type": "non_fast_forward"},
        {"type": "required_linear_history"},
        pull_request_rule(0),
        {"type": "required_status_checks", "parameters": {
            "strict_required_status_checks_policy": settings.get("require_up_to_date", False),
            "required_status_checks": [{"context": c} for c in checks],
        }},
    ])
    rulesets[APPROVAL_RULESET] = ruleset(APPROVAL_RULESET, [pull_request_rule(1)], [
        {"actor_type": "User", "actor_id": user_id(login), "bypass_mode": "pull_request"}
        for login in sorted({login for _, login in people})])
    return rulesets


def required_checks(rulesets):
    return [c["context"] for rule in rulesets[DEFAULT_RULESET]["rules"] if rule["type"] == "required_status_checks"
            for c in rule["parameters"]["required_status_checks"]]


def reported_checks(repo, ref):
    runs = gh_api("repos/{}/commits/{}/check-runs".format(repo, ref), "--paginate", "--jq", ".check_runs[].name")
    statuses = gh_api("repos/{}/commits/{}/status".format(repo, ref), "--jq", ".statuses[].context")
    return set(runs.split("\n") + statuses.split("\n")) - {""}


def latest_merged_pull_request(repo, branch):
    pulls = gh_json("repos/{}/pulls?state=closed&base={}&sort=updated&direction=desc&per_page=30".format(repo, branch))
    merged = [p for p in pulls if p.get("merged_at")]
    return max(merged, key=lambda p: p["merged_at"]) if merged else None


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


def check_branch_protection(update, repo):
    """The default branch is protected by the rulesets from desired_rulesets
    (and no others whose names end in MANAGED), and no longer by classic branch
    protection."""
    desired = desired_rulesets(repo)
    branch = gh_api("repos/{}".format(repo), "--jq", ".default_branch").strip()
    existing = {r["name"]: r["id"] for r in gh_json("repos/{}/rulesets".format(repo))
                if r.get("source_type") == "Repository"
                and r["name"].endswith(MANAGED)}

    # Requiring checks that pull requests don't report would block them all,
    # so don't start protecting the branch until they do. (Not the branch
    # itself: Participation is only reported on pull requests, and squashing
    # or rebasing makes new commits.)
    if DEFAULT_RULESET not in existing:
        pull = latest_merged_pull_request(repo, branch)
        if pull is None:
            return ["no merged pull requests to {} to see which checks they report, so not adding rulesets".format(branch)]
        missing = [c for c in required_checks(desired) if c not in reported_checks(repo, pull["head"]["sha"])]
        if missing:
            return ["the latest merged pull request (#{}) doesn't report {}, so not adding rulesets".format(
                pull["number"], ", ".join(missing))]

    problems = []
    for name, wanted in desired.items():
        if name not in existing:
            if not update:
                problems.append("no ruleset {!r}".format(name))
                continue
            gh_api("-X", "POST", "repos/{}/rulesets".format(repo), input=wanted)
            print("  fixed: created the ruleset {!r}".format(name))
        elif not contains(wanted, gh_json("repos/{}/rulesets/{}".format(repo, existing[name]))):
            if not update:
                problems.append("ruleset {!r} differs from factory.py".format(name))
                continue
            gh_api("-X", "PUT", "repos/{}/rulesets/{}".format(repo, existing[name]), input=wanted)
            print("  fixed: updated the ruleset {!r}".format(name))
    for name in set(existing) - set(desired):
        if not update:
            problems.append("ruleset {!r} isn't wanted by factory.py".format(name))
            continue
        gh_api("-X", "DELETE", "repos/{}/rulesets/{}".format(repo, existing[name]))
        print("  fixed: deleted the ruleset {!r}".format(name))
    if problems:
        return problems

    # The rules in effect on the branch (anyone with read access can see
    # these) must include all of the above before classic branch protection
    # can go.
    effective = gh_json("repos/{}/rules/branches/{}".format(repo, branch))
    for rule in (rule for r in desired.values() for rule in r["rules"]):
        if not any(contains(rule, r) for r in effective):
            problems.append("rule {} isn't in effect on {}".format(rule["type"], branch))
    if problems:
        return problems

    # Reading classic branch protection needs admin access; without it, this
    # part isn't checked.
    try:
        classic = gh_json("repos/{}/branches/{}/protection".format(repo, branch), allow_404=True)
    except RuntimeError:
        classic = None
    if classic is not None:
        if not update:
            return ["{} still has classic branch protection (redundant)".format(branch)]
        gh_api("-X", "DELETE", "repos/{}/branches/{}/protection".format(repo, branch))
        print("  fixed: deleted classic branch protection")
    return []


REPO_CHECKS = [check_bot_access, check_branch_protection]


def settings(shortnames, update):
    """Returns whether all settings are (now) correct."""
    ok = True
    for shortname in shortnames:
        repo = "{}/{}".format(ORG, shortname)
        print(repo)
        for check in REPO_CHECKS:
            try:
                problems = check(update, repo)
            except RuntimeError as e:
                problems = [str(e)]
            for problem in problems:
                print("  problem: {}".format(problem))
            ok = ok and not problems
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

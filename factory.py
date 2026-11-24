#!/usr/bin/env python

import argparse, base64, os, subprocess, uuid, json, requests

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
        if variable in ("not_these_templates", "readme"):
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


# Repository settings on GitHub, checked and fixed by --settings. See
# https://github.com/whatwg/misc-server/issues/107.
ENVIRONMENT = "production"
R2_SECRETS = ["R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ENDPOINT"]
# Where the R2 secret values are kept: a private repository only admins can read.
R2_SECRETS_FILE = ("whatwg/admin", "cloudflare-r2.json")
BOT = "whatbot"


def gh_api(*args, input=None):
    result = subprocess.run(["gh", "api", *args], input=input, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("gh api {}: {}".format(" ".join(args), result.stderr.strip()))
    return result.stdout


def load_r2_secrets():
    """The R2 secret values: from environment variables if all are set, else
    from cloudflare-r2.json in whatwg/admin."""
    if all(os.environ.get(name) for name in R2_SECRETS):
        return {name: os.environ[name] for name in R2_SECRETS}
    repo, path = R2_SECRETS_FILE
    content = gh_api("repos/{}/contents/{}".format(repo, path), "--jq", ".content")
    values = json.loads(base64.b64decode(content))
    missing = [name for name in R2_SECRETS if not values.get(name)]
    if missing:
        raise RuntimeError("{}/{} is missing: {}".format(repo, path, ", ".join(missing)))
    return {name: values[name] for name in R2_SECRETS}


def update_settings(shortname, r2_secrets):
    """Checks and fixes the GitHub settings of whatwg/<shortname>. Returns a
    list of problems that need a person."""
    repo = "whatwg/{}".format(shortname)
    problems = []

    # whatbot writes commit statuses (the Participation check), which needs
    # write access.
    permission = gh_api("repos/{}/collaborators/{}/permission".format(repo, BOT), "--jq", ".permission").strip()
    if permission not in ("admin", "write"):
        gh_api("-X", "PUT", "repos/{}/collaborators/{}".format(repo, BOT), "-f", "permission=push")
        print("  gave {} write access (was {})".format(BOT, permission))

    # The production environment holds the deploy credentials. Only main may
    # use it, and that only means "reviewed" if main is protected by a ruleset
    # requiring pull requests.
    rules = gh_api("repos/{}/rules/branches/main".format(repo), "--jq", ".[].type").split()
    if "pull_request" not in rules:
        problems.append("main has no ruleset requiring pull requests; not setting up the {} environment".format(ENVIRONMENT))
        return problems

    env = "repos/{}/environments/{}".format(repo, ENVIRONMENT)
    # Selected branches, not "protected branches only": that only counts
    # classic branch protection, and allows every branch if there is none.
    gh_api("-X", "PUT", env, "--input", "-", input=json.dumps(
        {"deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}}))
    policies = json.loads(gh_api(env + "/deployment-branch-policies"))["branch_policies"]
    if not any(p["name"] == "main" and p.get("type", "branch") == "branch" for p in policies):
        gh_api("-X", "POST", env + "/deployment-branch-policies", "-f", "name=main", "-f", "type=branch")
        print("  allowed main to use the {} environment".format(ENVIRONMENT))
    others = [p["name"] for p in policies if not (p["name"] == "main" and p.get("type", "branch") == "branch")]
    if others:
        problems.append("{} environment also allows: {}".format(ENVIRONMENT, ", ".join(others)))

    # Always (re)set the secrets, so that a run after updating
    # cloudflare-r2.json rotates them everywhere. Values go through stdin, so
    # they don't show up in the process list.
    for name in R2_SECRETS:
        subprocess.run(["gh", "secret", "set", name, "--repo", repo, "--env", ENVIRONMENT],
                       input=r2_secrets[name], text=True, capture_output=True, check=True)
    print("  set {}".format(", ".join(R2_SECRETS)))

    return problems


def update_all_settings(shortnames):
    try:
        r2_secrets = load_r2_secrets()
    except (RuntimeError, ValueError) as e:
        print("Can't get the R2 secrets: {}".format(e))
        return True
    failed = False
    for shortname in shortnames:
        print("whatwg/{}".format(shortname))
        try:
            problems = update_settings(shortname, r2_secrets)
        except (RuntimeError, subprocess.CalledProcessError) as e:
            problems = [str(e)]
        for problem in problems:
            print("  PROBLEM: {}".format(problem))
        failed = failed or bool(problems)
    return failed


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
    parser.add_argument("--settings", action="store_true", help="instead of files, check and fix the GitHub settings of the standards (whatbot access, production environment and its R2 secrets); use with --all or --single")
    args = parser.parse_args()

    if args.settings:
        if args.all:
            shortnames = all_shortnames()
        elif args.single:
            shortnames = [args.single[0]]
        else:
            parser.print_help()
            exit(1)
        exit(1 if update_all_settings(shortnames) else 0)

    if args.single and not args.create_prs:
        update_files(args.single[0], args.single[1])
    elif args.all:
        update_all_standards(args.create_prs)
    else:
        parser.print_help()
        exit(1)
    exit(0)

main()

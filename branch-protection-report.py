#!/usr/bin/env python
"""Lists the repositories of a GitHub organization and how their branches are
protected: classic branch protection on each protected branch, rulesets, and
the rules in effect on the default branch. Repositories with identical
protection of their default branch are grouped at the end.

Usage:
  ./branch-protection-report.py [--org whatwg] [--include-archived] [--json]

Needs `gh`, logged in. Reading classic branch protection needs admin access to
the repository; without it that part shows as "unknown".
"""

import argparse, json, subprocess, sys
from collections import defaultdict


class NotFound(Exception):
    pass


class Forbidden(Exception):
    pass


def gh(*args, paginate=False):
    command = ["gh", "api", *args] + (["--paginate", "--slurp"] if paginate else [])
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        if "HTTP 404" in result.stderr:
            raise NotFound(result.stderr.strip())
        if "HTTP 403" in result.stderr:
            raise Forbidden(result.stderr.strip())
        raise RuntimeError("gh api {}: {}".format(" ".join(args), result.stderr.strip()))
    data = json.loads(result.stdout)
    if paginate:  # --slurp gives a list of pages
        data = [item for page in data for item in page]
    return data


def summarize_classic(p):
    """The settings of a classic branch protection, as a flat dict."""
    def enabled(key):
        return bool(p.get(key, {}).get("enabled"))
    checks = p.get("required_status_checks") or {}
    contexts = sorted(set(checks.get("contexts", [])) | {c["context"] for c in checks.get("checks", [])})
    reviews = p.get("required_pull_request_reviews")
    restrictions = p.get("restrictions")
    return {
        "required_checks": contexts if checks else None,
        "checks_strict": checks.get("strict") if checks else None,
        "required_reviews": reviews.get("required_approving_review_count") if reviews else None,
        "dismiss_stale_reviews": reviews.get("dismiss_stale_reviews") if reviews else None,
        "code_owner_reviews": reviews.get("require_code_owner_reviews") if reviews else None,
        "last_push_approval": reviews.get("require_last_push_approval") if reviews else None,
        "enforce_admins": enabled("enforce_admins"),
        "linear_history": enabled("required_linear_history"),
        "allow_force_pushes": enabled("allow_force_pushes"),
        "allow_deletions": enabled("allow_deletions"),
        "conversation_resolution": enabled("required_conversation_resolution"),
        "signed_commits": enabled("required_signatures"),
        "lock_branch": enabled("lock_branch"),
        "push_restrictions": None if not restrictions else sorted(
            [u["login"] for u in restrictions.get("users", [])] +
            ["team:" + t["slug"] for t in restrictions.get("teams", [])] +
            ["app:" + a["slug"] for a in restrictions.get("apps", [])]),
    }


def summarize_rule(rule):
    """A rule in effect, as a short string."""
    params = rule.get("parameters") or {}
    t = rule["type"]
    if t == "pull_request":
        t += "(approvals={})".format(params.get("required_approving_review_count"))
    elif t == "required_status_checks":
        t += "({})".format(",".join(sorted(c["context"] for c in params.get("required_status_checks", []))))
    return t


def report_repo(org, repo):
    name = repo["name"]
    full = "{}/{}".format(org, name)
    default = repo["default_branch"]
    entry = {"repo": name, "archived": repo["archived"], "private": repo["private"],
             "default_branch": default, "protected_branches": {}, "rulesets": [],
             "rules_on_default_branch": None, "properties": {}}

    protected = gh("repos/{}/branches?protected=true&per_page=100".format(full), paginate=True)
    for branch in protected:
        try:
            entry["protected_branches"][branch["name"]] = summarize_classic(
                gh("repos/{}/branches/{}/protection".format(full, branch["name"])))
        except NotFound:
            # Protected only by a ruleset.
            entry["protected_branches"][branch["name"]] = "ruleset only"
        except Forbidden:
            entry["protected_branches"][branch["name"]] = "unknown (needs admin)"

    try:
        for r in gh("repos/{}/rulesets?includes_parents=true&per_page=100".format(full), paginate=True):
            entry["rulesets"].append("{} ({}, {})".format(r["name"], r.get("source_type", "?"), r.get("enforcement", "?")))
    except (NotFound, Forbidden):
        entry["rulesets"] = None
    try:
        entry["rules_on_default_branch"] = sorted(summarize_rule(r) for r in gh(
            "repos/{}/rules/branches/{}".format(full, default)))
    except (NotFound, Forbidden):
        pass
    try:
        entry["properties"] = {p["property_name"]: p["value"] for p in gh("repos/{}/properties/values".format(full))}
    except (NotFound, Forbidden):
        pass
    return entry


def print_entry(e):
    flags = [f for f, on in (("archived", e["archived"]), ("private", e["private"])) if on]
    print("{}{}".format(e["repo"], " ({})".format(", ".join(flags)) if flags else ""))
    if "error" in e:
        print("  error: {}".format(e["error"]))
        return
    print("  default branch: {}".format(e["default_branch"]))
    if not e["protected_branches"]:
        print("  protected branches: none")
    for branch, p in sorted(e["protected_branches"].items()):
        print("  protected branch {}:".format(branch))
        if isinstance(p, str):
            print("    {}".format(p))
            continue
        for key, value in p.items():
            if value not in (None, False, []):
                print("    {}: {}".format(key, value))
    if e["rulesets"]:
        print("  rulesets: {}".format("; ".join(e["rulesets"])))
    if e["rules_on_default_branch"]:
        print("  ruleset rules on {}: {}".format(e["default_branch"], ", ".join(e["rules_on_default_branch"])))
    props = {k: v for k, v in e["properties"].items() if v is not None}
    if props:
        print("  custom properties: {}".format(props))


def signature(e):
    """What protects the default branch, for grouping."""
    if "error" in e:
        return "error"
    classic = e["protected_branches"].get(e["default_branch"])
    return json.dumps({"classic": classic, "rules": e["rules_on_default_branch"] or []}, sort_keys=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--org", default="whatwg")
    parser.add_argument("--include-archived", action="store_true")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = parser.parse_args()

    repos = sorted(gh("orgs/{}/repos?per_page=100&type=all".format(args.org), paginate=True),
                   key=lambda r: r["name"].lower())
    if not args.include_archived:
        repos = [r for r in repos if not r["archived"]]

    entries = []
    for repo in repos:
        print("Reading {}...".format(repo["name"]), file=sys.stderr)
        try:
            entries.append(report_repo(args.org, repo))
        except (RuntimeError, NotFound, Forbidden) as e:
            entries.append({"repo": repo["name"], "archived": repo["archived"],
                            "private": repo["private"], "error": str(e)})

    if args.json:
        json.dump(entries, sys.stdout, indent=2)
        print()
        return

    for e in entries:
        print_entry(e)
    print()
    print("Repositories grouped by the protection of their default branch:")
    groups = defaultdict(list)
    for e in entries:
        groups[signature(e)].append(e["repo"])
    for sig, names in sorted(groups.items(), key=lambda g: -len(g[1])):
        if sig == "error":
            desc = "could not be read"
        else:
            s = json.loads(sig)
            classic = s["classic"]
            if classic is None:
                desc = "no classic protection"
            elif isinstance(classic, str):
                desc = classic
            else:
                desc = "classic: " + ", ".join("{}={}".format(k, v) for k, v in classic.items()
                                               if v not in (None, False, []))
            if s["rules"]:
                desc += "; rules: " + ", ".join(s["rules"])
        print()
        print("{} {}: {}".format(len(names), "repository" if len(names) == 1 else "repositories", desc))
        print("  " + " ".join(names))


if __name__ == "__main__":
    main()

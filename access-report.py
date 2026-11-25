#!/usr/bin/env python
"""Lists who can write to each repository of a GitHub organization: people
added to the repository directly, people in teams with access, and the
organization's owners (who can write everywhere). Repositories where fewer
than --min people (not counting bots or owners) can write are listed at the end.

Usage:
  ./access-report.py [--org whatwg] [--min 2] [--bots whatbot,...] [--include-archived] [--json]

Needs `gh`, logged in as someone who can see the repositories' collaborators
(admin access) and the organization's teams and members (gh with the read:org
scope). Temporary private forks for security advisories (<repo>-ghsa-...) are
skipped.
"""

import argparse, json, re, subprocess, sys

WRITE = ("admin", "maintain", "push")


def gh(*args):
    result = subprocess.run(["gh", "api", *args, "--paginate", "--slurp"], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("gh api {}: {}".format(" ".join(args), result.stderr.strip()))
    return [item for page in json.loads(result.stdout) for item in page]


def level(permissions):
    for p in WRITE:
        if permissions.get(p):
            return p
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--org", default="whatwg")
    parser.add_argument("--min", type=int, default=2, help="flag repositories with fewer people who can write (default 2)")
    parser.add_argument("--bots", default="whatbot", help="comma-separated logins to treat as bots, besides accounts of type Bot")
    parser.add_argument("--include-archived", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    bot_logins = {b.strip().lower() for b in args.bots.split(",") if b.strip()}

    def is_bot(user):
        return user.get("type") == "Bot" or user["login"].lower() in bot_logins or user["login"].endswith("[bot]")

    owners = sorted(u["login"] for u in gh("orgs/{}/members?role=admin&per_page=100".format(args.org)))
    teams = {}
    for team in gh("orgs/{}/teams?per_page=100".format(args.org)):
        teams[team["slug"]] = {u["login"] for u in gh("orgs/{}/teams/{}/members?per_page=100".format(args.org, team["slug"]))}

    repos = sorted(gh("orgs/{}/repos?per_page=100&type=all".format(args.org)), key=lambda r: r["name"].lower())
    repos = [r for r in repos if (args.include_archived or not r["archived"])
             and not re.search(r"-ghsa(-[a-z0-9]{4}){3}$", r["name"])]

    entries = []
    for repo in repos:
        name = repo["name"]
        print("Reading {}...".format(name), file=sys.stderr)
        full = "{}/{}".format(args.org, name)
        entry = {"repo": name, "direct": {}, "teams": {}, "bots": {}}
        try:
            for user in gh("repos/{}/collaborators?affiliation=direct&per_page=100".format(full)):
                p = level(user.get("permissions", {}))
                if p:
                    (entry["bots"] if is_bot(user) else entry["direct"])[user["login"]] = p
            for team in gh("repos/{}/teams?per_page=100".format(full)):
                p = level(team.get("permissions", {})) or (team.get("permission") if team.get("permission") in WRITE else None)
                if p:
                    members = sorted(teams.get(team["slug"], set()))
                    entry["teams"][team["slug"]] = {"permission": p, "members": members}
        except RuntimeError as e:
            entry["error"] = str(e)
        people = set(entry["direct"])
        for t in entry["teams"].values():
            people |= {m for m in t["members"] if m.lower() not in bot_logins and not m.endswith("[bot]")}
        entry["people"] = sorted(people)
        entries.append(entry)

    if args.json:
        json.dump({"owners": owners, "repositories": entries}, sys.stdout, indent=2)
        print()
        return

    print("Organization owners (can write to every repository): {}".format(", ".join(owners) or "none"))
    print()
    for e in entries:
        print(e["repo"])
        if "error" in e:
            print("  error: {}".format(e["error"]))
            continue
        if e["direct"]:
            print("  direct: {}".format(", ".join("{} ({})".format(u, p) for u, p in sorted(e["direct"].items()))))
        for slug, t in sorted(e["teams"].items()):
            print("  team {} ({}): {}".format(slug, t["permission"], ", ".join(t["members"]) or "no members"))
        if e["bots"]:
            print("  bots: {}".format(", ".join("{} ({})".format(u, p) for u, p in sorted(e["bots"].items()))))
        if not (e["direct"] or e["teams"] or e["bots"]):
            print("  only organization owners")

    print()
    print("Repositories where fewer than {} people (not counting bots or owners) can write:".format(args.min))
    few = [e for e in entries if "error" not in e and len(e["people"]) < args.min]
    for e in few:
        print("  {}: {}".format(e["repo"], ", ".join(e["people"]) or "nobody"))
    if not few:
        print("  none")
    errors = [e["repo"] for e in entries if "error" in e]
    if errors:
        print("Couldn't read: {}".format(", ".join(errors)))


if __name__ == "__main__":
    main()

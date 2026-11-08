#!/usr/bin/env python3
"""First publication using an authenticated GitHub CLI, without storing secrets."""

import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent


def run(*args, check=True):
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True)
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Comando falhou.")
    return result


def verify_protection(actual, expected):
    checks = actual.get("required_status_checks") or {}
    reviews = actual.get("required_pull_request_reviews")
    required = expected["required_status_checks"]
    return (checks.get("strict") is True and set(required["contexts"]).issubset(checks.get("contexts", []))
            and isinstance(reviews, dict) and reviews.get("dismiss_stale_reviews") is True
            and all(actual.get(key, {}).get("enabled") is True for key in
                    ("enforce_admins", "required_linear_history", "required_conversation_resolution"))
            and all(actual.get(key, {}).get("enabled") is False for key in ("allow_force_pushes", "allow_deletions")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--visibility", choices=("public", "private"), required=True)
    parser.add_argument("--gh-bin", default="gh", help="Caminho do GitHub CLI autenticado")
    args = parser.parse_args()

    def gh(*parts, check=True):
        return run(args.gh_bin, *parts, check=check)

    def api(path, *options):
        return json.loads(gh("api", path, *options).stdout)

    gh("auth", "status", "--hostname", "github.com")
    owner = api("user")["login"]
    if not re.fullmatch(r"[A-Za-z0-9-]+", owner):
        raise RuntimeError("Conta GitHub inválida.")
    repo = owner + "/turzx-linux"
    url = "https://github.com/" + repo
    if run("git", "branch", "--show-current").stdout.strip() != "main":
        raise RuntimeError("Execute na branch main após revisar e commitar o projeto.")
    if run("git", "status", "--porcelain").stdout.strip():
        raise RuntimeError("Há alterações sem commit. Revise e commite antes de publicar.")
    head = run("git", "rev-parse", "HEAD").stdout.strip()
    origin = run("git", "remote", "get-url", "origin", check=False)
    allowed = {url, url + ".git", "git@github.com:" + repo + ".git"}
    if origin.returncode == 0 and origin.stdout.strip() not in allowed:
        raise RuntimeError("O origin aponta para outro repositório; não foi alterado.")

    existing = gh("api", "repos/" + repo, check=False)
    if existing.returncode:
        if "HTTP 404" not in existing.stderr:
            raise RuntimeError(existing.stderr.strip())
        gh("repo", "create", repo, "--" + args.visibility, "--description",
           "Editor GTK para TURZX 3,5 no Linux: textos livres, gráficos e sensores CPU/GPU/RAM/rede.")
        print("Repositório criado:", url, flush=True)
    else:
        metadata = json.loads(existing.stdout)
        if metadata["private"] != (args.visibility == "private"):
            raise RuntimeError("A visibilidade do repositório existente difere da solicitada; nada foi alterado.")
        if metadata.get("size", 0) > 0:
            remote_head = api("repos/" + repo + "/git/ref/heads/main")["object"]["sha"]
            if remote_head != head:
                raise RuntimeError("O repositório existente tem outro commit. Use o fluxo normal por PR.")

    if origin.returncode:
        run("git", "remote", "add", "origin", url + ".git")
    # Scope the credential helper to this process; do not modify global Git config.
    helper = "!" + shlex.quote(args.gh_bin) + " auth git-credential"
    run("git", "-c", "credential.helper=", "-c", "credential.helper=" + helper,
        "push", "--set-upstream", url + ".git", "main:main")
    endpoint = "repos/" + repo
    if api(endpoint + "/git/ref/heads/main")["object"]["sha"] != head:
        raise RuntimeError("O commit remoto não corresponde ao commit local.")
    api(endpoint, "--method", "PATCH", "-f", "default_branch=main",
        "-F", "allow_squash_merge=true", "-F", "allow_rebase_merge=true", "-F", "allow_merge_commit=false")
    policy = ROOT / ".github/main-protection.json"
    protection = endpoint + "/branches/main/protection"
    api(protection, "--method", "PUT", "--input", str(policy))
    if not verify_protection(api(protection), json.loads(policy.read_text())):
        raise RuntimeError("O GitHub não confirmou toda a política de proteção.")
    print("Main protegida: PR, CI atualizado, sem force push/exclusão, inclusive administradores.", flush=True)

    for attempt in range(120):
        runs = json.loads(gh("run", "list", "--repo", repo, "--workflow", "linux.yml", "--commit", head,
                             "--limit", "5", "--json", "status,conclusion,url").stdout)
        if runs and runs[0]["status"] == "completed":
            if runs[0]["conclusion"] != "success":
                raise RuntimeError("O CI não passou. Corrija via PR: " + runs[0]["url"])
            print("CI aprovado:", runs[0]["url"])
            print("Publicado e verificado:", url)
            return 0
        if attempt % 6 == 0:
            print("Aguardando Linux CI…", flush=True)
        time.sleep(5)
    raise RuntimeError("Main protegida, mas o CI ainda não terminou. Confira: " + url + "/actions")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, KeyError, ValueError) as exc:
        print("Publicação incompleta: " + str(exc), file=sys.stderr)
        raise SystemExit(1)

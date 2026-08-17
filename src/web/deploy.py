from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from src.paths import ROOT
from src.web.publish import HOST, publish

ENV_PATH = ROOT / ".env"
PASSWORD_KEY = "PA_SITE_PASSWORD"
PASSWORD_LEN = 16
ALPHABET = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_password() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(PASSWORD_LEN))


def upsert_env(key: str, value: str) -> None:
    lines: list[str] = []
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    found = False
    out: list[str] = []
    for line in lines:
        if line.startswith(key + "="):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        if out and out[-1] != "":
            out.append("")
        out.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


def load_password() -> str:
    load_dotenv(ENV_PATH)
    return os.environ.get(PASSWORD_KEY) or ""


def rotate_password() -> str:
    """Replace PA_SITE_PASSWORD. Never prints other .env keys."""
    password = new_password()
    upsert_env(PASSWORD_KEY, password)
    os.environ[PASSWORD_KEY] = password
    return password


def ensure_password() -> tuple[str, bool]:
    """Return (password, created). Never prints other .env keys."""
    existing = load_password()
    if existing:
        return existing, False
    return rotate_password(), True


def stage_deploy(dest: Path, *, fetch_quotes: bool = True) -> Path:
    site = publish(dest / "snapshot", fetch_quotes=fetch_quotes)
    shutil.copy(HOST / "vercel.json", dest / "vercel.json")
    shutil.copy(HOST / "login.html", dest / "login.html")
    api = dest / "api"
    api.mkdir()
    shutil.copy(HOST / "api" / "gate.js", api / "gate.js")
    shutil.copy(HOST / "api" / "login.js", api / "login.js")
    shutil.copy(site / "bundle.json", api / "bundle.json")
    shutil.copytree(site / "static", dest / "static")
    return dest


def _logged_in() -> bool:
    result = subprocess.run(
        ["npx", "--yes", "vercel", "whoami"],
        check=False,
        capture_output=True,
        text=True,
    )
    out = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0 and "Logged out" not in out


def deploy(*, fetch_quotes: bool = True, new_password: bool = False) -> int:
    if new_password:
        password = rotate_password()
        print(f"new {PASSWORD_KEY} (keep this): {password}")
    else:
        password, created = ensure_password()
        if created:
            print(f"new {PASSWORD_KEY} (keep this): {password}")
    with tempfile.TemporaryDirectory(prefix="pa-vercel-") as tmp:
        stage_deploy(Path(tmp), fetch_quotes=fetch_quotes)
        env = os.environ.copy()
        env[PASSWORD_KEY] = password
        cmd = [
            "npx",
            "--yes",
            "vercel",
            "deploy",
            "--yes",
            "-e",
            f"{PASSWORD_KEY}={password}",
        ]
        if _logged_in():
            cmd.append("--prod")
        else:
            cmd.append("--temporary")
            print("vercel: not logged in; creating a temporary deployment you can claim")
        result = subprocess.run(cmd, cwd=tmp, env=env)
        return int(result.returncode)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Publish a password-gated snapshot to Vercel")
    parser.add_argument(
        "--no-quotes",
        action="store_true",
        help="skip Groww CMP (offline)",
    )
    parser.add_argument(
        "--new-password",
        action="store_true",
        help="replace PA_SITE_PASSWORD (16 chars) and redeploy",
    )
    args = parser.parse_args(argv)
    return deploy(fetch_quotes=not args.no_quotes, new_password=args.new_password)


if __name__ == "__main__":
    raise SystemExit(main())

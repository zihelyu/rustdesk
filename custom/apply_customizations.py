#!/usr/bin/env python3
"""Apply display customizations to a disposable build checkout."""

from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    patch = root / "custom/display-name.patch"
    if not patch.is_file():
        print(f"Missing customization patch: {patch}", file=sys.stderr)
        return 1
    result = subprocess.run(
        ["git", "apply", "--check", str(patch)],
        cwd=root, capture_output=True, text=True,
    )
    if result.returncode == 0:
        subprocess.run(["git", "apply", str(patch)], cwd=root, check=True)
        print("Applied custom/display-name.patch.", flush=True)
    else:
        reverse = subprocess.run(
            ["git", "apply", "--reverse", "--check", str(patch)],
            cwd=root, capture_output=True, text=True,
        )
        if reverse.returncode != 0:
            print(result.stderr, file=sys.stderr)
            print(
                "Customization patch conflicts with this source revision. "
                "Update custom/display-name.patch before building; no unbranded fallback is allowed.",
                file=sys.stderr,
            )
            return 1
        print("Display patch already applied to this checkout.", flush=True)
    subprocess.run(
        [sys.executable, str(root / "custom/apply_branding.py")],
        cwd=root, check=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        print(f"Customization failed: {error}", file=sys.stderr)
        raise SystemExit(error.returncode)

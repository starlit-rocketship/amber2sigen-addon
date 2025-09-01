#!/usr/bin/env python3
# sigen_make_env.py
# Prompt for Amber/Sigen credentials and create amber2sigen.env

import getpass
from pathlib import Path
import os

def write_env(path: Path, values: dict, overwrite: bool):
    if path.exists() and not overwrite:
        raise SystemExit(f"Refusing to overwrite existing file: {path}\nPass --overwrite to replace it.")
    lines = []
    for k, v in values.items():
        v = (v or "").replace("\n", "")
        if any(ch in v for ch in [' ', '#', '"', "'", '$']):
            v_out = f'"{v}"'
        else:
            v_out = v
        lines.append(f"{k}={v_out}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass

def main():
    print("Amber → Sigen Environment Setup")
    amber_token = getpass.getpass("Enter Amber API Token: ")
    sigen_user = input("Enter Sigen username/email: ").strip()
    sigen_pass_enc = getpass.getpass("Enter Sigen encoded password (SIGEN_PASS_ENC): ")
    sigen_device_id = input("Enter Sigen device ID (SIGEN_DEVICE_ID): ").strip()

    values = {
        "AMBER_TOKEN": amber_token,
        "SIGEN_USER": sigen_user,
        "SIGEN_PASS_ENC": sigen_pass_enc,
        "SIGEN_DEVICE_ID": sigen_device_id,
        "INTERVAL": "30",
        "TZ_OVERRIDE": "Australia/Adelaide",
        "ALIGN": "end",
        "PLAN_NAME": "Amber Live",
        "ADVANCED": "predicted",
        "USE_CURRENT": "1",
    }

    env_path = Path("amber2sigen.env")
    write_env(env_path, values, overwrite=True)
    print(f"Wrote {env_path.resolve()}")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# sigen_make_env.py
# Create a clean, comment-free env file for amber_to_sigen + run.sh

import argparse
import base64
import hashlib
import os
import sys
import random
from pathlib import Path

def pkcs7_pad(b: bytes, block: int = 16) -> bytes:
    pad = block - (len(b) % block)
    return b + bytes([pad]) * pad

def encrypt_password_aes_ecb_pkcs7(plaintext: str, user_device_id: str) -> str:
    try:
        from Crypto.Cipher import AES  # pycryptodome
    except Exception:
        sys.exit("ERROR: pycryptodome is required. Install with:  pip install pycryptodome")
    key = hashlib.md5(user_device_id.encode("utf-8")).digest()
    cipher = AES.new(key, AES.MODE_ECB)
    ct = cipher.encrypt(pkcs7_pad(plaintext.encode("utf-8")))
    return base64.b64encode(ct).decode("ascii")

def generate_device_id() -> str:
    """Return a random 13-digit string (like Sigen userDeviceId)."""
    return "".join(random.choices("0123456789", k=13))

def write_env(path: Path, values: dict, overwrite: bool):
    if path.exists() and not overwrite:
        sys.exit(f"Refusing to overwrite existing file: {path}\nPass --overwrite to replace it.")
    lines = []
    for k in [
        "AMBER_TOKEN",
        "SIGEN_USER",
        "SIGEN_DEVICE_ID",
        "SIGEN_PASS_ENC",
        "INTERVAL",
        "TZ_OVERRIDE",
        "ALIGN",
        "PLAN_NAME",
        "ADVANCED",
        "USE_CURRENT",
    ]:
        v = values.get(k, "")
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
    ap = argparse.ArgumentParser(description="Create a clean amber2sigen.env for run.sh + amber_to_sigen.py")
    ap.add_argument("--user", required=True, help="Sigen account email/username")
    ap.add_argument("--password", required=True, help="Sigen account plaintext password")
    ap.add_argument("--device-id", help="Sigen userDeviceId (the value the app uses). If omitted, generate random 13-digit ID")
    ap.add_argument("--env-path", default="amber2sigen.env", help="Output env file path (default: amber2sigen.env)")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite env file if it exists")

    # sane defaults
    ap.add_argument("--interval", type=int, choices=[5,30], default=30, help="Default INTERVAL (5 or 30)")
    ap.add_argument("--tz", default="Australia/Adelaide", help="Default TZ_OVERRIDE")
    ap.add_argument("--align", choices=["start","end"], default="end", help="Default ALIGN for labeling")
    ap.add_argument("--plan-name", default="Amber Live", help="Default PLAN_NAME label")
    ap.add_argument("--advanced", choices=["low","predicted","high"], default="predicted", help="Default ADVANCED buy price selector")
    ap.add_argument("--use-current", type=int, choices=[0,1], default=1, help="Default USE_CURRENT (1=enable /prices/current override)")

    args = ap.parse_args()

    device_id = args.device_id or generate_device_id()
    enc = encrypt_password_aes_ecb_pkcs7(args.password, device_id)

    values = {
        "AMBER_TOKEN": "",  # left blank for user to fill
        "SIGEN_USER": args.user,
        "SIGEN_DEVICE_ID": device_id,
        "SIGEN_PASS_ENC": enc,
        "INTERVAL": str(args.interval),
        "TZ_OVERRIDE": args.tz,
        "ALIGN": args.align,
        "PLAN_NAME": args.plan_name,
        "ADVANCED": args.advanced,
        "USE_CURRENT": str(args.use_current),
    }

    out = Path(args.env_path)
    write_env(out, values, args.overwrite)
    print(f"Wrote {out.resolve()}")
    print(f"Generated SIGEN_DEVICE_ID={device_id}")
    print("Next steps:")
    print("  1) Edit AMBER_TOKEN= in the env file to your Amber API key.")
    print("  2) In run.sh, ensure it does:  source ./amber2sigen.env")
    print("  3) Test:  bash run.sh --dry-run")

if __name__ == "__main__":
    main()
#!/usr/bin/env python3
import os, subprocess, sys, logging, shlex

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

def red(s: str) -> str:
    return s[:4] + "…" if s and len(s) > 8 else "REDACTED"

def main():
    # Read env populated by run.sh/bashio
    amber_token = os.environ.get("AMBER_TOKEN", "")
    sigen_bearer = os.environ.get("SIGEN_BEARER", "")
    sigen_user = os.environ.get("SIGEN_USER", "")
    sigen_dev = os.environ.get("SIGEN_DEVICE_ID", "")
    sigen_enc = os.environ.get("SIGEN_PASS_ENC", "")

    logging.info("Env check: AMBER_TOKEN=%s SIGEN_USER=%s SIGEN_DEVICE_ID=%s SIGEN_BEARER=%s SIGEN_PASS_ENC=%s",
                 red(amber_token), sigen_user, sigen_dev, red(sigen_bearer), red(sigen_enc))

    # Forward flags to upstream
    cmd = ["python3", "/opt/amber2sigen/amber_to_sigen.py"] + sys.argv[1:]
    logging.info("Exec: %s", " ".join(map(shlex.quote, cmd)))
    res = subprocess.run(cmd)
    sys.exit(res.returncode)

if __name__ == "__main__":
    main()

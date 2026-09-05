"""
Deploy a CMCR instance to a real network (localnet / studionet /
testnet_asimov, per gltest.config.yaml).

This reuses gltest's documented factory API rather than a separate
CLI/SDK path -- Studio Mode is explicitly documented as suitable for
"testnet deployment", not just testing, so this is the same tooling
tests/integration/ uses, just driven for a one-off real deploy
instead of an assertion-bearing test.

Usage:
    python scripts/deploy_cmcr.py \\
        --predicate "Python 2 has reached end-of-life" \\
        --canonical-url "https://www.python.org/doc/sunset-python-2/" \\
        --corroborating-url "https://devguide.python.org/versions/" \\
        --required-signal "a statement that Python 2 is end-of-life" \\
        --falsifier "a statement that Python 2 is still supported" \\
        --challenge-window-days 7 \\
        --network studionet

Requires GenLayer Studio running for --network studionet/localnet,
or funded account keys in .env for --network testnet_asimov (see
gltest.config.yaml). After deploying, record the result in
artifacts/ -- see artifacts/README.md for the expected format.
"""

import argparse
import json
import sys
from pathlib import Path

from gltest import get_contract_factory, get_default_account


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predicate", required=True)
    parser.add_argument("--canonical-url", required=True)
    parser.add_argument("--corroborating-url", required=True)
    parser.add_argument("--required-signal", required=True)
    parser.add_argument("--falsifier", required=True)
    parser.add_argument("--challenge-window-days", type=int, default=7)
    parser.add_argument(
        "--network",
        default="localnet",
        help="Must match a network defined in gltest.config.yaml",
    )
    parser.add_argument(
        "--artifact-name",
        default=None,
        help="Filename (without extension) to write under artifacts/. "
        "Defaults to a slug derived from --predicate.",
    )
    return parser.parse_args()


def _slug(text: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in text][:60]
    slug = "".join(keep).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "commitment"


def main() -> int:
    args = parse_args()

    factory = get_contract_factory("cmcr")  # matches contracts/cmcr.py -> class Contract
    account = get_default_account()

    contract = factory.deploy(
        args=[
            args.predicate,
            args.canonical_url,
            args.corroborating_url,
            args.required_signal,
            args.falsifier,
            args.challenge_window_days,
        ],
        account=account,
    )

    # NOTE ON contract ADDRESS: the genlayer-test quick-start docs show
    # `contract.account == get_default_account()` after deploying with
    # the default account -- i.e. `.account` reflects the *deploying*
    # account, not necessarily the contract's own on-chain address.
    # There's no confirmed attribute name here for "the contract's own
    # address" as distinct from the deployer, so rather than guess
    # wrong, this prints the raw contract object/deploy receipt for you
    # to inspect once, then update this script with whichever attribute
    # (commonly something like `.address` or via the deploy receipt)
    # actually holds it in your installed genlayer-test version.
    print("Raw contract object (inspect to find the actual deployed address):")
    print(repr(contract))

    record = {
        "network": args.network,
        "deployer": str(account),
        "predicate": args.predicate,
        "canonical_url": args.canonical_url,
        "corroborating_url": args.corroborating_url,
        "required_signal": args.required_signal,
        "falsifier": args.falsifier,
        "challenge_window_days": args.challenge_window_days,
    }

    print(json.dumps(record, indent=2))

    artifacts_dir = Path(__file__).resolve().parent.parent / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    name = args.artifact_name or f"{args.network}-{_slug(args.predicate)}"
    out_path = artifacts_dir / f"{name}.json"
    out_path.write_text(json.dumps(record, indent=2) + "\n")
    print(f"\nWrote {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

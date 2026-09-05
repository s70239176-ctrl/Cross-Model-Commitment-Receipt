"""
Direct-mode tests for CMCR's state machine and access control.

These never touch resolve(), so no gl.nondet.web / gl.nondet.exec_prompt
calls happen and no mock_web/mock_llm is needed -- direct_deploy runs
the contract's Python in-memory and direct_vm.prank()/expect_revert()
exercise every guard rail deterministically in milliseconds.

SDK_VERSION is pinned explicitly (see below) because gltest's
auto-detected "latest" currently resolves to a GenVM release that no
longer ships the asset gltest 0.29.2 expects.

Payable calls use direct_vm.value = <amount>, not a value= kwarg on
the method itself -- direct mode's calldata-roundtrip proxy rejects
value as a keyword argument to the contract method (it isn't part of
the method's own signature; VMContext carries it out-of-band, the
same way real GenVM message.value does). direct_vm.value is reset to
0 after each payable call so it doesn't leak into the next one.

Run: pytest tests/direct/test_lifecycle.py -v
"""

import json

CONTRACT = "contracts/cmcr.py"

# gltest's direct-mode SDK loader (gltest/direct/sdk_loader.py in
# genlayer-test 0.29.2) downloads a "genvm-universal.tar.xz" asset from
# genlayerlabs/genvm's GitHub releases. When no version is pinned, it
# resolves "latest" via a redirect, which currently lands on
# v0.3.0-rc7 -- but starting at v0.3.0-rc0, that asset was renamed to
# "genvm-runners-all.tar.xz", so the download 404s.
# v0.2.16 is the newest release that still publishes the old asset
# name, and this contract's pinned runner hash (from its `Depends`
# header) has been confirmed present inside it. Bump this once
# gltest ships a fix for the new asset name, or once you've verified
# a newer version also contains this contract's runner hash.
SDK_VERSION = "v0.2.16"

BASE_ARGS = [
    "Python 2 has reached end-of-life",  # predicate
    "https://www.python.org/doc/sunset-python-2/",  # canonical_url
    "https://devguide.python.org/versions/",  # corroborating_url
    "a statement that Python 2 is end-of-life",  # required_signal
    "a statement that Python 2 is still supported",  # falsifier
]


def _deploy(direct_deploy, direct_vm, owner, challenge_window_days=7):
    with direct_vm.prank(owner):
        return direct_deploy(
            CONTRACT, *BASE_ARGS, challenge_window_days, sdk_version=SDK_VERSION
        )


def _send(direct_vm, sender, value, fn):
    """Call a payable contract method as `sender` with `value` GEN."""
    with direct_vm.prank(sender):
        direct_vm.value = value
        try:
            return fn()
        finally:
            direct_vm.value = 0


def test_constructor_rejects_blank_predicate(direct_deploy, direct_vm, direct_owner):
    with direct_vm.prank(direct_owner):
        with direct_vm.expect_revert("predicate required"):
            direct_deploy(
                CONTRACT,
                "",
                BASE_ARGS[1],
                BASE_ARGS[2],
                BASE_ARGS[3],
                BASE_ARGS[4],
                7,
                sdk_version=SDK_VERSION,
            )


def test_constructor_rejects_non_http_url(direct_deploy, direct_vm, direct_owner):
    with direct_vm.prank(direct_owner):
        with direct_vm.expect_revert("canonical_url must be http(s)"):
            direct_deploy(
                CONTRACT,
                BASE_ARGS[0],
                "not-a-url",
                BASE_ARGS[2],
                BASE_ARGS[3],
                BASE_ARGS[4],
                7,
                sdk_version=SDK_VERSION,
            )


def test_constructor_rejects_window_too_short(direct_deploy, direct_vm, direct_owner):
    with direct_vm.prank(direct_owner):
        with direct_vm.expect_revert("challenge_window_days must be in [1, 90]"):
            direct_deploy(CONTRACT, *BASE_ARGS, 0, sdk_version=SDK_VERSION)


def test_constructor_rejects_window_too_long(direct_deploy, direct_vm, direct_owner):
    with direct_vm.prank(direct_owner):
        with direct_vm.expect_revert("challenge_window_days must be in [1, 90]"):
            direct_deploy(CONTRACT, *BASE_ARGS, 91, sdk_version=SDK_VERSION)


def test_commit_by_non_committer_reverts(direct_deploy, direct_vm, direct_owner, direct_alice):
    contract = _deploy(direct_deploy, direct_vm, direct_owner)
    with direct_vm.expect_revert("only committer"):
        _send(direct_vm, direct_alice, 100, contract.commit)
    case = json.loads(contract.get_case())
    assert case["status"] == "open"


def test_commit_requires_nonzero_value(direct_deploy, direct_vm, direct_owner):
    contract = _deploy(direct_deploy, direct_vm, direct_owner)
    with direct_vm.expect_revert("commit requires value"):
        _send(direct_vm, direct_owner, 0, contract.commit)


def test_committer_cannot_challenge_self(direct_deploy, direct_vm, direct_owner):
    contract = _deploy(direct_deploy, direct_vm, direct_owner)
    _send(direct_vm, direct_owner, 100, contract.commit)
    with direct_vm.expect_revert("committer cannot challenge"):
        _send(direct_vm, direct_owner, 20, contract.challenge)


def test_challenge_requires_nonzero_value(direct_deploy, direct_vm, direct_owner, direct_alice):
    contract = _deploy(direct_deploy, direct_vm, direct_owner)
    _send(direct_vm, direct_owner, 100, contract.commit)
    with direct_vm.expect_revert("challenge requires value"):
        _send(direct_vm, direct_alice, 0, contract.challenge)


def test_double_challenge_reverts(direct_deploy, direct_vm, direct_owner, direct_alice, direct_bob):
    contract = _deploy(direct_deploy, direct_vm, direct_owner)
    _send(direct_vm, direct_owner, 100, contract.commit)
    _send(direct_vm, direct_alice, 20, contract.challenge)
    with direct_vm.expect_revert("not committed"):
        _send(direct_vm, direct_bob, 30, contract.challenge)
    case = json.loads(contract.get_case())
    assert case["status"] == "challenged"
    # direct_alice is plain bytes (gltest's create_address() fallback),
    # not a genlayer Address -- str() on raw bytes gives a Python bytes
    # repr, not the "0x..." hex format get_case()'s str(self.challenger)
    # produces. Import Address lazily (only on sys.path after
    # direct_deploy has run) to convert it for a correct comparison.
    from genlayer.py.types import Address

    assert case["challenger"] == str(Address(direct_alice))
    assert case["challenge_stake"] == "20"


def test_extend_window_is_committer_only(direct_deploy, direct_vm, direct_owner, direct_alice):
    contract = _deploy(direct_deploy, direct_vm, direct_owner, challenge_window_days=1)
    _send(direct_vm, direct_owner, 100, contract.commit)
    with direct_vm.prank(direct_alice):
        with direct_vm.expect_revert("only the committer may extend the window"):
            contract.extend_window(5)
    with direct_vm.prank(direct_owner):
        contract.extend_window(5)  # succeeds for the actual committer


def test_extend_window_blocked_after_challenge(
    direct_deploy, direct_vm, direct_owner, direct_alice
):
    contract = _deploy(direct_deploy, direct_vm, direct_owner, challenge_window_days=1)
    _send(direct_vm, direct_owner, 100, contract.commit)
    _send(direct_vm, direct_alice, 20, contract.challenge)
    with direct_vm.prank(direct_owner):
        with direct_vm.expect_revert(
            "window can only be extended before the first challenge"
        ):
            contract.extend_window(5)


def test_mark_expired_before_window_close_reverts(direct_deploy, direct_vm, direct_owner):
    contract = _deploy(direct_deploy, direct_vm, direct_owner, challenge_window_days=7)
    _send(direct_vm, direct_owner, 100, contract.commit)
    with direct_vm.prank(direct_owner):
        with direct_vm.expect_revert("challenge window has not closed yet"):
            contract.mark_expired()


def test_mark_expired_after_window_close_succeeds(direct_deploy, direct_vm, direct_owner):
    """direct_vm.warp() time-travels the VM's clock -- no real waiting
    required, unlike the equivalent manual-Studio scenario in
    tests/integration/TESTS.md."""
    contract = _deploy(direct_deploy, direct_vm, direct_owner, challenge_window_days=1)
    _send(direct_vm, direct_owner, 100, contract.commit)
    direct_vm.warp("2030-01-01T00:00:00Z")
    with direct_vm.prank(direct_owner):
        contract.mark_expired()
    case = json.loads(contract.get_case())
    assert case["status"] == "unchallenged-expired"


def test_challenge_after_window_close_reverts(direct_deploy, direct_vm, direct_owner, direct_alice):
    contract = _deploy(direct_deploy, direct_vm, direct_owner, challenge_window_days=1)
    _send(direct_vm, direct_owner, 100, contract.commit)
    direct_vm.warp("2030-01-01T00:00:00Z")
    with direct_vm.expect_revert("challenge window has closed"):
        _send(direct_vm, direct_alice, 20, contract.challenge)


def test_resolve_before_challenge_or_expiry_reverts(direct_deploy, direct_vm, direct_owner):
    contract = _deploy(direct_deploy, direct_vm, direct_owner)
    _send(direct_vm, direct_owner, 100, contract.commit)
    with direct_vm.prank(direct_owner):
        with direct_vm.expect_revert("not eligible for resolution (status=committed)"):
            contract.resolve()

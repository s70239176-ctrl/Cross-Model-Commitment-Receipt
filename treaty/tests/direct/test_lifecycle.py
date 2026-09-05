"""
Direct-mode tests for CMCR's state machine and access control.

These never touch resolve(), so no gl.nondet.web / gl.nondet.exec_prompt
calls happen and no mock_web/mock_llm is needed -- direct_deploy runs
the contract's Python in-memory and direct_vm.prank()/expect_revert()
exercise every guard rail deterministically in milliseconds.

Run: pytest tests/direct/test_lifecycle.py -v
"""

import json

CONTRACT = "contracts/cmcr.py"

BASE_ARGS = [
    "Python 2 has reached end-of-life",  # predicate
    "https://www.python.org/doc/sunset-python-2/",  # canonical_url
    "https://devguide.python.org/versions/",  # corroborating_url
    "a statement that Python 2 is end-of-life",  # required_signal
    "a statement that Python 2 is still supported",  # falsifier
]


def _deploy(direct_deploy, direct_vm, owner, challenge_window_days=7):
    with direct_vm.prank(owner):
        return direct_deploy(CONTRACT, *BASE_ARGS, challenge_window_days)


def test_constructor_rejects_blank_predicate(direct_deploy, direct_vm, direct_owner):
    with direct_vm.prank(direct_owner):
        with direct_vm.expect_revert("predicate required"):
            direct_deploy(
                CONTRACT, "", BASE_ARGS[1], BASE_ARGS[2], BASE_ARGS[3], BASE_ARGS[4], 7
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
            )


def test_constructor_rejects_out_of_range_window(direct_deploy, direct_vm, direct_owner):
    with direct_vm.prank(direct_owner):
        with direct_vm.expect_revert("challenge_window_days must be in [1, 90]"):
            direct_deploy(CONTRACT, *BASE_ARGS, 0)
        with direct_vm.expect_revert("challenge_window_days must be in [1, 90]"):
            direct_deploy(CONTRACT, *BASE_ARGS, 91)


def test_commit_by_non_committer_reverts(direct_deploy, direct_vm, direct_owner, direct_alice):
    contract = _deploy(direct_deploy, direct_vm, direct_owner)
    with direct_vm.prank(direct_alice):
        with direct_vm.expect_revert("only committer"):
            contract.commit(value=100)
    case = json.loads(contract.get_case())
    assert case["status"] == "open"


def test_commit_requires_nonzero_value(direct_deploy, direct_vm, direct_owner):
    contract = _deploy(direct_deploy, direct_vm, direct_owner)
    with direct_vm.prank(direct_owner):
        with direct_vm.expect_revert("commit requires value"):
            contract.commit(value=0)


def test_committer_cannot_challenge_self(direct_deploy, direct_vm, direct_owner):
    contract = _deploy(direct_deploy, direct_vm, direct_owner)
    with direct_vm.prank(direct_owner):
        contract.commit(value=100)
        with direct_vm.expect_revert("committer cannot challenge"):
            contract.challenge(value=20)


def test_challenge_requires_nonzero_value(direct_deploy, direct_vm, direct_owner, direct_alice):
    contract = _deploy(direct_deploy, direct_vm, direct_owner)
    with direct_vm.prank(direct_owner):
        contract.commit(value=100)
    with direct_vm.prank(direct_alice):
        with direct_vm.expect_revert("challenge requires value"):
            contract.challenge(value=0)


def test_double_challenge_reverts(direct_deploy, direct_vm, direct_owner, direct_alice, direct_bob):
    contract = _deploy(direct_deploy, direct_vm, direct_owner)
    with direct_vm.prank(direct_owner):
        contract.commit(value=100)
    with direct_vm.prank(direct_alice):
        contract.challenge(value=20)
    with direct_vm.prank(direct_bob):
        with direct_vm.expect_revert("not committed"):
            contract.challenge(value=30)
    case = json.loads(contract.get_case())
    assert case["status"] == "challenged"
    # str(direct_alice) is assumed to match gl.Address.__str__()'s format
    # (i.e. get_case()'s str(self.challenger)) -- verify this equality
    # holds in your installed genlayer-test version; if not, compare
    # case["challenger"] against whatever direct_alice actually stringifies to.
    assert case["challenger"] == str(direct_alice)
    assert case["challenge_stake"] == "20"


def test_extend_window_is_committer_only(direct_deploy, direct_vm, direct_owner, direct_alice):
    contract = _deploy(direct_deploy, direct_vm, direct_owner, challenge_window_days=1)
    with direct_vm.prank(direct_owner):
        contract.commit(value=100)
    with direct_vm.prank(direct_alice):
        with direct_vm.expect_revert("only the committer may extend the window"):
            contract.extend_window(5)
    with direct_vm.prank(direct_owner):
        contract.extend_window(5)  # succeeds for the actual committer


def test_extend_window_blocked_after_challenge(
    direct_deploy, direct_vm, direct_owner, direct_alice
):
    contract = _deploy(direct_deploy, direct_vm, direct_owner, challenge_window_days=1)
    with direct_vm.prank(direct_owner):
        contract.commit(value=100)
    with direct_vm.prank(direct_alice):
        contract.challenge(value=20)
    with direct_vm.prank(direct_owner):
        with direct_vm.expect_revert(
            "window can only be extended before the first challenge"
        ):
            contract.extend_window(5)


def test_mark_expired_before_window_close_reverts(direct_deploy, direct_vm, direct_owner):
    contract = _deploy(direct_deploy, direct_vm, direct_owner, challenge_window_days=7)
    with direct_vm.prank(direct_owner):
        contract.commit(value=100)
        with direct_vm.expect_revert("challenge window has not closed yet"):
            contract.mark_expired()


def test_resolve_before_challenge_or_expiry_reverts(direct_deploy, direct_vm, direct_owner):
    contract = _deploy(direct_deploy, direct_vm, direct_owner)
    with direct_vm.prank(direct_owner):
        contract.commit(value=100)
        with direct_vm.expect_revert("not eligible for resolution (status=committed)"):
            contract.resolve()

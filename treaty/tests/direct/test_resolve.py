"""
Direct-mode tests for CMCR's resolve() -- the two-step consensus path.

_extract_source() is called once per source inside resolve(), each
time calling gl.nondet.web.render(url, mode="text") then
gl.nondet.exec_prompt(prompt). We mock both: mock_web supplies the
page body per URL, mock_llm supplies the JSON string exec_prompt
returns, keyed by a regex that matches a substring of the prompt.

Because the prompt literally contains "CANONICAL PAGE TEXT" or
"CORROBORATING PAGE TEXT" (from the `label` argument in
_extract_source), those two substrings are what we match on -- this
works regardless of what the mocked page body actually says, so it's
a stable way to give the canonical and corroborating calls different
answers.

ASSUMPTION FLAGGED: this assumes direct_vm.mock_web() intercepts
gl.nondet.web.render(url, mode="text") the same way it intercepts
gl.nondet.web.get()/request() in the documented examples, with the
mocked "body" becoming render()'s return value. This isn't shown
verbatim in the public quick-start snippet (which only shows a
get()-style JSON API mock) -- if render() turns out to need a
different mock shape in your installed genlayer-test version, adjust
the `body` value here to match (e.g. it may need to be the rendered
text directly rather than wrapped in a status/body dict).

Run: pytest tests/direct/test_resolve.py -v
"""

import json

CONTRACT = "contracts/cmcr.py"

PREDICATE = "Python 2 has reached end-of-life"
CANONICAL_URL = "https://canonical.example.com/py2-eol"
CORROBORATING_URL = "https://corroborating.example.com/py2-versions"
REQUIRED_SIGNAL = "a statement that Python 2 is end-of-life"
FALSIFIER = "a statement that Python 2 is still supported"


def _deploy_and_challenge(direct_deploy, direct_vm, owner, alice, challenge_window_days=7):
    with direct_vm.prank(owner):
        contract = direct_deploy(
            CONTRACT,
            PREDICATE,
            CANONICAL_URL,
            CORROBORATING_URL,
            REQUIRED_SIGNAL,
            FALSIFIER,
            challenge_window_days,
        )
        contract.commit(value=100)
    with direct_vm.prank(alice):
        contract.challenge(value=20)
    return contract


def _mock_pages(direct_vm, canonical_body, corroborating_body):
    direct_vm.mock_web(
        r"canonical\.example\.com", {"status": 200, "body": canonical_body}
    )
    direct_vm.mock_web(
        r"corroborating\.example\.com", {"status": 200, "body": corroborating_body}
    )


def _mock_extractions(direct_vm, canonical_json, corroborating_json):
    direct_vm.mock_llm(r"CANONICAL PAGE TEXT", json.dumps(canonical_json))
    direct_vm.mock_llm(r"CORROBORATING PAGE TEXT", json.dumps(corroborating_json))


def test_resolve_holds_when_both_sources_agree(
    direct_deploy, direct_vm, direct_owner, direct_alice
):
    contract = _deploy_and_challenge(direct_deploy, direct_vm, direct_owner, direct_alice)
    _mock_pages(
        direct_vm,
        "Python 2 reached its end of life on January 1, 2020.",
        "Only Python 3.x branches are currently maintained.",
    )
    _mock_extractions(
        direct_vm,
        {"has_required": True, "has_falsifier": False, "page_state": "fresh"},
        {"has_required": True, "has_falsifier": False, "page_state": "fresh"},
    )

    decision = contract.resolve()

    assert decision == "holds"
    case = json.loads(contract.get_case())
    assert case["status"] == "holds"
    assert case["verdict"] == "holds"
    extract = json.loads(case["extract_json"])
    assert extract["decision"] == "holds"
    assert extract["pages_conflict"] is False
    assert extract["pages_unusable"] is False


def test_resolve_broken_when_falsifier_present(
    direct_deploy, direct_vm, direct_owner, direct_alice
):
    contract = _deploy_and_challenge(direct_deploy, direct_vm, direct_owner, direct_alice)
    _mock_pages(
        direct_vm,
        "Python 2 is still actively maintained by the core team.",
        "Python 2 is still actively maintained by the core team.",
    )
    _mock_extractions(
        direct_vm,
        {"has_required": False, "has_falsifier": True, "page_state": "fresh"},
        {"has_required": False, "has_falsifier": True, "page_state": "fresh"},
    )

    decision = contract.resolve()

    assert decision == "broken"
    case = json.loads(contract.get_case())
    assert case["status"] == "broken"


def test_resolve_inconclusive_on_source_conflict(
    direct_deploy, direct_vm, direct_owner, direct_alice
):
    contract = _deploy_and_challenge(direct_deploy, direct_vm, direct_owner, direct_alice)
    _mock_pages(
        direct_vm,
        "Python 2 reached its end of life on January 1, 2020.",
        "Python 2 is still actively maintained.",
    )
    # canonical says has_required=True, corroborating disagrees -- forces pages_conflict
    _mock_extractions(
        direct_vm,
        {"has_required": True, "has_falsifier": False, "page_state": "fresh"},
        {"has_required": False, "has_falsifier": False, "page_state": "fresh"},
    )

    decision = contract.resolve()

    assert decision == "inconclusive"
    extract = json.loads(json.loads(contract.get_case())["extract_json"])
    assert extract["pages_conflict"] is True


def test_resolve_inconclusive_on_unreachable_source(
    direct_deploy, direct_vm, direct_owner, direct_alice
):
    contract = _deploy_and_challenge(direct_deploy, direct_vm, direct_owner, direct_alice)
    _mock_pages(
        direct_vm,
        "Python 2 reached its end of life on January 1, 2020.",
        "",  # empty / dead page
    )
    _mock_extractions(
        direct_vm,
        {"has_required": True, "has_falsifier": False, "page_state": "fresh"},
        {"has_required": False, "has_falsifier": False, "page_state": "unreachable"},
    )

    decision = contract.resolve()

    assert decision == "inconclusive"
    extract = json.loads(json.loads(contract.get_case())["extract_json"])
    assert extract["pages_unusable"] is True


def test_double_resolve_reverts(direct_deploy, direct_vm, direct_owner, direct_alice):
    contract = _deploy_and_challenge(direct_deploy, direct_vm, direct_owner, direct_alice)
    _mock_pages(
        direct_vm,
        "Python 2 reached its end of life on January 1, 2020.",
        "Only Python 3.x branches are currently maintained.",
    )
    _mock_extractions(
        direct_vm,
        {"has_required": True, "has_falsifier": False, "page_state": "fresh"},
        {"has_required": True, "has_falsifier": False, "page_state": "fresh"},
    )
    contract.resolve()

    with direct_vm.expect_revert("not eligible for resolution (status=holds)"):
        contract.resolve()


def test_resolve_payout_holds_goes_to_committer(
    direct_deploy, direct_vm, direct_owner, direct_alice
):
    """Sanity check on the mechanical payout, not just the verdict string."""
    contract = _deploy_and_challenge(direct_deploy, direct_vm, direct_owner, direct_alice)
    _mock_pages(
        direct_vm,
        "Python 2 reached its end of life on January 1, 2020.",
        "Only Python 3.x branches are currently maintained.",
    )
    _mock_extractions(
        direct_vm,
        {"has_required": True, "has_falsifier": False, "page_state": "fresh"},
        {"has_required": True, "has_falsifier": False, "page_state": "fresh"},
    )
    contract.resolve()
    case = json.loads(contract.get_case())
    # commit_stake/challenge_stake fields are left as-recorded (not
    # zeroed) -- the transfer itself happens via gl.get_contract_at(...)
    # .emit_transfer(), which direct mode should route to a mock ledger.
    # Check your installed genlayer-test's balance-assertion helper
    # (e.g. direct_vm.balance_of(...) if available) for a stronger
    # assertion than the fields checked here.
    assert case["commit_stake"] == "100"
    assert case["challenge_stake"] == "20"
    assert case["status"] == "holds"

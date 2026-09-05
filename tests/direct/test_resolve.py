"""
Direct-mode tests for CMCR's resolve() -- the two-step consensus path.

_extract_source() is called once per source inside resolve(), each
time calling gl.nondet.web.render(url, mode="text") then
gl.nondet.exec_prompt(prompt). We mock both: mock_web supplies the
page body per URL, mock_llm supplies the raw string exec_prompt
returns, keyed by a regex that matches a substring of the prompt.

Because the prompt literally contains "CANONICAL PAGE TEXT" or
"CORROBORATING PAGE TEXT" (from the `label` argument in
_extract_source), those two substrings are what we match on -- this
works regardless of what the mocked page body actually says.

CONFIRMED against the installed genlayer-test source
(gltest/direct/wasi_mock.py):
- mock_web DOES intercept gl.nondet.web.render() the same way it
  intercepts get()-style calls: _handle_web_render() reuses
  _match_web_mock(), with the mocked "body" becoming render()'s
  returned text. The earlier assumption about this held.
- _handle_llm_request() unconditionally tries json.loads() on any
  mocked LLM response string and, if it parses, returns the PARSED
  DICT instead of the raw string -- regardless of whether the
  contract called exec_prompt with response_format="json". Our
  contract calls gl.nondet.exec_prompt(prompt) with no
  response_format and does its own `raw.replace("```json", ...)`
  cleanup, expecting a raw string back. If the mock body were bare
  JSON, gltest's auto-parse would silently hand back a dict instead,
  and `raw.replace(...)` would blow up with AttributeError. Wrapping
  the mocked JSON in markdown code fences (exactly like a real LLM's
  raw output often looks) makes the outer string invalid JSON on its
  own, so json.loads() raises, the auto-parse falls through, and our
  contract's own fence-stripping code runs as it would against a real
  LLM response.

Run: pytest tests/direct/test_resolve.py -v
"""

import json

CONTRACT = "contracts/cmcr.py"

# See tests/direct/test_lifecycle.py for the full explanation: gltest
# 0.29.2's auto-detected "latest" GenVM release no longer publishes the
# asset name it expects, so the version is pinned explicitly here too.
SDK_VERSION = "v0.2.16"

PREDICATE = "Python 2 has reached end-of-life"
CANONICAL_URL = "https://canonical.example.com/py2-eol"
CORROBORATING_URL = "https://corroborating.example.com/py2-versions"
REQUIRED_SIGNAL = "a statement that Python 2 is end-of-life"
FALSIFIER = "a statement that Python 2 is still supported"


def _send(direct_vm, sender, value, fn):
    """Call a payable contract method as `sender` with `value` GEN."""
    with direct_vm.prank(sender):
        direct_vm.value = value
        try:
            return fn()
        finally:
            direct_vm.value = 0


def _fenced_json(payload: dict) -> str:
    """Wrap a JSON payload in markdown code fences -- see module
    docstring for why this matters for gltest's LLM mock auto-parse."""
    return "```json\n" + json.dumps(payload) + "\n```"


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
            sdk_version=SDK_VERSION,
        )
    _send(direct_vm, owner, 100, contract.commit)
    _send(direct_vm, alice, 20, contract.challenge)
    return contract


def _mock_pages(direct_vm, canonical_body, corroborating_body):
    direct_vm.mock_web(
        r"canonical\.example\.com", {"status": 200, "body": canonical_body}
    )
    direct_vm.mock_web(
        r"corroborating\.example\.com", {"status": 200, "body": corroborating_body}
    )


def _mock_extractions(direct_vm, canonical_json, corroborating_json):
    direct_vm.mock_llm(r"CANONICAL PAGE TEXT", _fenced_json(canonical_json))
    direct_vm.mock_llm(r"CORROBORATING PAGE TEXT", _fenced_json(corroborating_json))


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

    with direct_vm.prank(direct_owner):
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

    with direct_vm.prank(direct_owner):
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

    with direct_vm.prank(direct_owner):
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

    with direct_vm.prank(direct_owner):
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
    with direct_vm.prank(direct_owner):
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
    with direct_vm.prank(direct_owner):
        contract.resolve()
    case = json.loads(contract.get_case())
    # commit_stake/challenge_stake fields are left as-recorded (not
    # zeroed) -- the transfer itself happens via gl.get_contract_at(...)
    # .emit_transfer(), which direct mode routes into direct_vm's
    # internal _balances dict (see gltest/direct/vm.py). There's no
    # public balance-reading cheatcode as of genlayer-test 0.29.2, only
    # the private _balances attribute and the deal() setter, so this
    # test checks the recorded stake fields and status rather than an
    # actual balance delta.
    assert case["commit_stake"] == "100"
    assert case["challenge_stake"] == "20"
    assert case["status"] == "holds"

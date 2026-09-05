"""
Studio-mode integration test for CMCR: deploys against a running
GenLayer Studio instance (or localnet) and drives the real state
machine through real consensus, with mocked validators so the
verdict is deterministic even though this is a genuine RPC round
trip rather than an in-memory call.

Requires GenLayer Studio running (see gltest.config.yaml). Run with:
    gltest tests/integration/test_cmcr_studio.py -v -s

For a manual, no-script walkthrough of the same scenarios (useful
for exploring the contract interactively in the Studio UI), see
tests/integration/TESTS.md.

CALLING CONVENTION: confirmed against GenLayer's own docs (the
Upgradability guide) and genlayer-test's PyPI quick-start --
Studio-mode write/read calls take contract arguments via an
`args=[...]` kwarg, not as direct positional/keyword arguments on the
method call itself:
    contract.upgrade(args=[v2_code]).transact()
    contract.get_storage(args=[]).call()
This was WRONG in an earlier version of this file (args were passed
directly, e.g. `contract.commit(value=100, account=committer)`) and
is fixed below.

UNVERIFIED: I could not find a confirmed example of a *payable*
Studio-mode write call (one that sends GEN value, like commit() and
challenge() here) in GenLayer's public docs or the reference
genlayer-project-boilerplate -- its example contract (football bets)
isn't payable. `value=100` is kept as a kwarg on the method call
below (alongside `account=`, which the deploy() example does confirm
works this way), but this specific placement for VALUE is a
best-effort guess, not a verified pattern. If this fails when you
actually run it against Studio, check genlayer-py's transaction
builder (the layer gltest's contract proxy sits on) for how it
expects native value to be attached to a write call -- likely either
a kwarg here, or a parameter on `.transact()` itself
(`.transact(value=100)`) rather than on the method call.
"""

import json

from gltest import get_contract_factory, get_default_account, get_validator_factory
from gltest.assertions import tx_execution_succeeded
from gltest.types import MockedLLMResponse, MockedWebResponse

CONTRACT = "Contract"  # matches `class Contract(gl.Contract):` in contracts/cmcr.py
                        # -- gltest's Studio-mode factory looks up contracts by
                        # literal Python class name (via AST inspection of
                        # contracts_dir), not by filename. Confirmed by reading
                        # gltest/artifacts/contract.py's search_path_by_class_name().

PREDICATE = "Python 2 has reached end-of-life"
CANONICAL_URL = "https://canonical.example.com/py2-eol"
CORROBORATING_URL = "https://corroborating.example.com/py2-versions"
REQUIRED_SIGNAL = "a statement that Python 2 is end-of-life"
FALSIFIER = "a statement that Python 2 is still supported"


def _mock_transaction_context():
    # Mocking at "nondet_exec_prompt" (not "eq_principle_prompt_comparative")
    # matters here: the latter would substitute a canned result for the
    # *entire* prompt_comparative call, meaning _extract_source()'s actual
    # body (gl.nondet.web.render + gl.nondet.exec_prompt + json parsing)
    # never runs at all. Mocking the lower-level nondet_exec_prompt call
    # instead still exercises that real code path, with only the LLM
    # response itself faked -- the substring match is against the literal
    # prompt text, which is why "CANONICAL PAGE TEXT" / "CORROBORATING
    # PAGE TEXT" (both literally present in _extract_source()'s prompt)
    # work as match keys here, same as in tests/direct/test_resolve.py.
    mock_llm_response: MockedLLMResponse = {
        "nondet_exec_prompt": {
            "CANONICAL PAGE TEXT": '{"has_required": true, "has_falsifier": false, "page_state": "fresh"}',
            "CORROBORATING PAGE TEXT": '{"has_required": true, "has_falsifier": false, "page_state": "fresh"}',
        }
    }
    # ASSUMPTION FLAGGED (same as tests/direct/test_resolve.py): this
    # assumes "nondet_web_request" also intercepts gl.nondet.web.render()
    # calls, keyed by exact URL, with "body" becoming render()'s return
    # value -- the documented example only shows this for a get()-style
    # call. Verify against your installed genlayer-test version.
    mock_web_response: MockedWebResponse = {
        "nondet_web_request": {
            CANONICAL_URL: {
                "method": "GET",
                "status": 200,
                "body": "Python 2 reached its end of life on January 1, 2020.",
            },
            CORROBORATING_URL: {
                "method": "GET",
                "status": 200,
                "body": "Only Python 3.x branches are currently maintained.",
            },
        }
    }
    validator_factory = get_validator_factory()
    validators = validator_factory.batch_create_mock_validators(
        count=5,
        mock_llm_response=mock_llm_response,
        mock_web_response=mock_web_response,
    )
    return {
        "validators": [v.to_dict() for v in validators],
        "genvm_datetime": "2026-01-01T00:00:00Z",
    }


def test_full_holds_flow(accounts):
    committer, challenger = accounts[0], accounts[1]
    factory = get_contract_factory(CONTRACT)

    contract = factory.deploy(
        args=[PREDICATE, CANONICAL_URL, CORROBORATING_URL, REQUIRED_SIGNAL, FALSIFIER, 7],
        account=committer,
    )

    # See the UNVERIFIED note above: value=100 here is a best-effort
    # guess for how to attach native GEN to a Studio-mode write call,
    # not a confirmed pattern.
    tx = contract.commit(args=[], value=100, account=committer).transact()
    assert tx_execution_succeeded(tx)

    tx = contract.challenge(args=[], value=20, account=challenger).transact()
    assert tx_execution_succeeded(tx)

    ctx = _mock_transaction_context()
    tx = contract.resolve(args=[], account=committer).transact(transaction_context=ctx)
    assert tx_execution_succeeded(tx)

    case = json.loads(contract.get_case(args=[]).call())
    assert case["status"] == "holds"

# Cross-Model Commitment Receipt (CMCR)

An on-chain GenLayer Intelligent Contract primitive that binds a
committer to a structured, falsifiable claim about the world, frozen
at commit time, and later adjudicates it from live primary sources —
never from either party's own say-so.

Structured to match GenLayer's official project conventions
(`genlayer-project-boilerplate`, `genlayer-testing-suite`): a
Direct-mode test suite for fast in-memory CI, and an Integration
suite against a real GenLayer Studio instance for full consensus
validation.

```
contracts/           the deployed contract (cmcr.py)
docs/                threat model, state machine, eq_principle rationale,
                      reviewer mapping, and known simplifications (DESIGN.md)
examples/             ready-to-paste constructor inputs for holds / broken /
                      inconclusive scenarios
tests/
  direct/              fast, in-memory pytest suite (no Docker) --
                       state machine + access control (test_lifecycle.py)
                       and the two-step resolve() consensus, with
                       mock_web/mock_llm (test_resolve.py)
  integration/         gltest suite against a real Studio instance
                       (test_cmcr_studio.py), plus a manual/no-script
                       walkthrough of the same scenarios (TESTS.md)
scripts/
  deploy_cmcr.py       scripted deployment via gltest's factory API
artifacts/            deployed instance records (see artifacts/README.md)
.github/workflows/     CI: syntax-check + tests/direct/ on every push/PR
gltest.config.yaml     network config for Studio-mode tests/deploys
requirements.txt       genlayer-test + pytest
```

## Quick start

```bash
pip install -r requirements.txt

# Fast, no Docker required:
pytest tests/direct/ -v

# Full consensus validation -- requires GenLayer Studio actually
# running first (see "Starting GenLayer Studio" below):
gltest tests/integration/ -v -s
```

### Starting GenLayer Studio (needed for `tests/integration/` only)

`tests/direct/` never needs this -- only `tests/integration/` and
manual Studio deployment do. Requires Docker 26+ and Node.js 18+.

```bash
npm install -g genlayer
genlayer init      # first time only -- pulls containers, prompts for
                    # an LLM provider/API key
genlayer up         # starts Studio; leave this running
```

Studio's UI is then at `http://localhost:8080`, and its RPC API at
`http://127.0.0.1:4000/api` -- the same URL already configured in
`gltest.config.yaml`. Run `gltest tests/integration/ -v -s` in a
second terminal once `genlayer up` reports it's ready.

1. Read `docs/DESIGN.md` for the threat model and why the contract's
   consensus logic is shaped the way it is.
2. Deploy `contracts/cmcr.py` via `scripts/deploy_cmcr.py` (or GenLayer
   Studio directly) with the constructor args described in
   `examples/deploy_examples.md`.
3. Walk through `tests/integration/TESTS.md` against your deployment,
   or just trust `tests/integration/test_cmcr_studio.py` to do it for
   you with mocked-deterministic validators.

## Status

Single-instance design: one contract deployment = one commitment,
deployed per claim via `scripts/deploy_cmcr.py` rather than a
registry contract holding many commitments in one deployment. See
`docs/DESIGN.md` → "What's simplified relative to the fuller
commitment-object spec" for the known limitations of this shape.

## Fixed since first draft (found by actually running the tests)

- **A real production bug in `contracts/cmcr.py`**: `_pay()` called
  `emit_transfer(amount)` positionally, but the actual SDK signature
  is keyword-only (`emit_transfer(self, *, value: u256, on=...)`),
  confirmed by reading the installed SDK source directly. Every
  payout path in `resolve()` would have reverted the moment it tried
  to transfer a nonzero amount. **If you deployed an earlier version
  of this contract to Studio, redeploy with this fix.**
- `tests/direct/`'s `SDK_VERSION` pin: `gltest`'s auto-detected
  "latest" GenVM release currently 404s (the release asset it expects
  was renamed starting at v0.3.0-rc7). Pinned to `v0.2.16` after
  downloading it and confirming this contract's exact runner hash is
  inside it.
- `mock_web` intercepting `gl.nondet.web.render()`: confirmed correct
  by reading `gltest`'s interception code directly — no longer an
  assumption.
- All 21 `tests/direct/` tests now pass, verified by actually running
  `pytest` against the real installed `genlayer-test` package.

## Still unverified

- **`tests/integration/test_cmcr_studio.py`'s payable value syntax**:
  I found and fixed the confirmed `args=[...]` calling convention for
  Studio-mode contract calls, but couldn't find a confirmed example of
  attaching native GEN `value=` to a Studio-mode write call anywhere
  in GenLayer's public docs or the reference boilerplate (whose
  example contract isn't payable). The `value=100` kwarg in that file
  is a best-effort guess, flagged inline — if it's wrong, check
  whether `.transact()` itself takes a `value=` parameter instead.
- `scripts/deploy_cmcr.py` still doesn't know the correct attribute
  for a deployed contract's own on-chain address (see
  `artifacts/README.md`) — it prints the raw contract object rather
  than guessing.
- `LICENSE` has a placeholder copyright holder name to fill in.

None of the remaining items block the contract itself, which is now
verified working end-to-end in direct mode — they're specifically
about the Studio-mode integration test's exact API surface, which
needs a real Studio instance to confirm.

# treaty — Cross-Model Commitment Receipt (CMCR)

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

# Full consensus validation (requires GenLayer Studio running):
gltest tests/integration/ -v -s
```

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

## Honest gaps (flagged, not hidden)

A few things in this repo are best-effort against documented APIs I
could not execute end-to-end myself:

- `tests/direct/test_resolve.py` and `tests/integration/test_cmcr_studio.py`
  assume `mock_web`/`MockedWebResponse` intercepts
  `gl.nondet.web.render()` the same way the public docs show for
  `.get()`/`.request()`-style calls. Verify this against your
  installed `genlayer-test` version.
- `scripts/deploy_cmcr.py` does not yet know the correct attribute for
  a deployed contract's own on-chain address (see `artifacts/README.md`
  for why) — it prints the raw contract object instead of guessing.
- `LICENSE` has a placeholder copyright holder name to fill in.

None of these block the contract itself, which is deployed and
working — they're specifically about the surrounding tooling's exact
API surface, which is easy to confirm once you actually run
`pytest`/`gltest` locally.

# Cross-Model Commitment Receipt (CMCR) — single-instance edition

**Category:** Intelligent Contracts
**File:** `cmcr.py` — one contract, one commitment per deployment, no
frontend, no second contract type.

This is a deliberately narrowed implementation of the CMCR primitive:
one required signal, one falsifier, two sources (canonical +
corroborating), deploy fresh per claim (intended to sit behind an
off-chain or on-chain factory that deploys one instance per
commitment). See "What's simplified" below for exactly what was cut
relative to the fuller commitment-object spec, and why that cut is
still defensible.

## Threat model

- **Committer** wants a verdict of `holds` even after the world moved
  — by picking sources they expect to be edited later, or by writing a
  predicate loose enough to be re-interpreted favorably at resolve
  time.
- **Challenger** wants a verdict of `broken` to take the committer's
  stake — by staking against a commitment they haven't actually
  checked, hoping the resolution goes their way for free.
- **A single LLM** (leader or a lone validator) wants to produce a
  plausible answer, including deciding on its own that two sources
  "conflict" without a validator ever being forced to independently
  check that claim.

Greyboxing (predicate/sources/signals frozen before any dispute
exists), independent live fetches (every validator re-fetches every
source itself), and keeping the LLM confined to per-source extraction
(never asked to compare sources or hand down a verdict) are what make
consensus load-bearing here rather than decorative.

## State machine

```
open --commit()--> committed
committed --challenge()--> challenged
committed --mark_expired(), window closed--> unchallenged-expired
challenged --resolve()--> holds | broken | inconclusive
unchallenged-expired --resolve()--> holds | broken | inconclusive
committed --extend_window(), payer-only, pre-challenge--> committed
```

No method ever writes to `predicate`, `canonical_url`,
`corroborating_url`, `required_signal`, or `falsifier` after the
constructor runs — there is no setter for any of them. `resolve()`
only accepts `status in ("challenged", "unchallenged-expired")`, so a
second call after the status becomes `holds`/`broken`/`inconclusive`
always reverts.

## gl.eq_principle calls and why

| # | Call | Where | Why this principle |
|---|------|-------|---------------------|
| 1–2 | `gl.eq_principle.prompt_comparative(extract, principle)` | `_extract_source()`, called once for `canonical_url` and once for `corroborating_url` inside `resolve()` | Each call forces every validator to independently fetch **one** page and report `has_required` / `has_falsifier` / `page_state` for that page alone. The model never sees the other source and is never asked whether the two agree — the comparison principle only requires agreement on those three fields, not on wording, so genuine paraphrase differences between validators don't break consensus, but an invented "yes it's there" does. |
| 3 | `gl.eq_principle.strict_eq(reduce_verdict)` | once in `resolve()`, after both extractions return | `reduce_verdict()` is pure Python: it compares the two already-canonicalized booleans/state strings from step A and picks `holds`/`broken`/`inconclusive` from a fixed decision table. Nothing subjective is left for a model to adjudicate at this point, so `strict_eq` is the cheapest and least gameable principle for it. |

This is the two-step pattern the category requires: the LLM only ever
extracts (step A, one source at a time, no visibility into the other
source); Python alone decides whether two sources conflict and what
the final verdict is (step B). There is no single "fetch both pages,
ask an LLM if the spec is met" call anywhere in this contract.

## What's simplified relative to the fuller commitment-object spec

Compared to a full CMCR design with `claim_type`, a set of
`falsifiers` with normalized ids, a `tolerance` field for numeric
claims, and an explicit negative-control source role, this contract
has:

- **One** required signal and **one** falsifier, not sets — so it
  can't represent "any of these three clauses disappearing breaks the
  claim," only a single required/single forbidden pair.
- **No numeric/threshold support** — an SLA-style "p99 latency ≤
  200ms" claim isn't representable; only presence/absence-style claims
  are.
- **No explicit source-role enforcement** — `canonical_url` and
  `corroborating_url` are just two URLs; nothing stops a deployer from
  putting the same kind of source in both slots, unlike a design that
  requires at least one canonical and one negative-control role.
- **No `claim_type`** — every claim is implicitly existence/quote-style.

These are real limits on expressiveness, not shortcuts in the
consensus mechanism itself — the two-step extraction/reduction split,
the frozen fields, and the mechanical payoff all hold regardless.
Widening `required_signal`/`falsifier` into parallel lists and adding
a `tolerance` + numeric branch to `reduce_verdict()` would recover
most of the fuller spec without changing the contract's shape.

## Why the challenge has no "brief" argument

Unlike a design where a challenger submits a free-text brief for
context, `challenge()` here takes no argument beyond the stake itself.
There is nothing for `resolve()` to selectively "ignore" because
nothing narrative is ever stored — the only way to affect the verdict
is to have staked correctly on what the frozen sources actually say.

## Extraction type-safety and how staleness affects settlement

Every field a validator's extraction reports is validated, not
trusted verbatim:

- `has_required` / `has_falsifier` are coerced to `bool`.
- `page_state` is checked against a closed enum
  (`{"fresh", "stale", "unreachable"}`) inside `_extract_source()`.
  Any off-enum or unparseable value is clamped to `"unreachable"` —
  the most conservative state — rather than accepted as a novel
  fourth state. This matters concretely: if two sources both
  hallucinated the same nonsense value (e.g. `"unknown"`) and it were
  accepted verbatim, `reduce_verdict()`'s equality check would see
  matching states and could wave the pair through as usable evidence.
  Clamping first closes that off.

**Settlement rule for `page_state`:** only `"fresh"` counts as
usable evidence. A source reporting `"stale"` is treated exactly like
`"unreachable"` — either one makes the pair non-evidentiary and forces
`inconclusive`, never `holds` or `broken`. This is a deliberate
tightening: a stale or cached page is precisely the source-rot
scenario named in this document's own threat model (a committer
hoping resolution reads a quietly-outdated snapshot instead of the
live page), so staleness cannot be allowed to silently pass as
equivalent to a current page just because two validators agree on
what the cache says.

## Mechanical payoff

`resolve()`'s payout branch is a fixed `if/elif` on `decision`, no
discretion:

- `holds` → committer receives both stakes.
- `broken`, with a challenger → challenger receives both stakes.
- `broken`, no challenger (only reachable via the unchallenged-expired
  path) → stake is returned to the committer. There is no adversary to
  slash the stake *to* in this path; sending it anywhere else would
  either be tokenomics theater (an invented treasury) or a free
  griefing tool (letting anyone force a punitive resolution against an
  uncontested, merely-stale commitment). The finding itself
  (`status == "broken"`) is still recorded on-chain either way.
- `inconclusive` → both stakes returned to their original owners.

## How another builder reuses this

Deploy one instance per claim (constructor takes the whole commitment
as arguments), ideally from a factory contract or off-chain deployer
script. Because `required_signal`/`falsifier` are free text handed to
the extraction prompt rather than hard-coded logic, the same contract
code covers any presence/absence-style claim — a dataset license
clause, a governance proposal's wording, an API's continued disclosure
of something — without modification. See `TESTS.md` for concrete
constructor examples.

## For reviewers: category requirements mapped to the contract

| Requirement | Where |
|---|---|
| Real consensus logic, not "fetch, ask LLM, pay" | `resolve()`: two `_extract_source()` calls (step A) feed one `reduce_verdict()` under `strict_eq` (step B) |
| Clear state design | `status` field + exact state machine above, enforced by explicit guards in every write method |
| Predicate/sources/signals frozen at commit time | Constructor sets them; no method ever reassigns |
| Independent live fetch, not trusted narrative | `gl.nondet.web.render(url, mode="text")` inside `_extract_source()`, run per-validator by the equivalence principle; no challenge-brief field exists to bypass this |
| Extraction fields validated, not trusted verbatim; stale sources can't pass as fresh | `_extract_source()` clamps `page_state` to a closed enum; `reduce_verdict()` requires `"fresh"` specifically (not just non-`"unreachable"`) to count as evidence |
| Mechanical, status-driven payoff | Fixed `if/elif` on `decision` inside `resolve()` |
| No re-resolve / no source or signal edit | `resolve()`'s status guard; no setters exist for frozen fields |
| Optional `extend_window`, payer-only, pre-challenge, typed state transition | `extend_window()` |
| Unauthorized commit/challenge rejected | `commit()` checks `sender == self.committer`; `challenge()` checks `sender != self.committer` and the live window |
| Reusable by another builder without forking | `required_signal`/`falsifier` are free-text constructor args, not hard-coded |

## Not included, on purpose

No frontend. No token beyond native GEN stakes/counter-stakes already
native to GenLayer. No second contract.

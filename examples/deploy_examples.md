# Deploy examples

Ready-to-paste constructor arguments for `contracts/cmcr.py`:
`(predicate, canonical_url, corroborating_url, required_signal,
falsifier, challenge_window_days=7)`.

These are also walked through, with the full call sequence and
expected balances, in `tests/TESTS.md` tests 1–3.

## `holds` example

```
predicate            = "Python 2 has reached end-of-life and is no longer maintained by the CPython core team"
canonical_url         = "https://www.python.org/doc/sunset-python-2/"
corroborating_url     = "https://devguide.python.org/versions/"
required_signal       = "a statement that Python 2 is end-of-life / no longer supported"
falsifier             = "a statement that Python 2 is still actively supported or maintained"
challenge_window_days = 7
```

## `broken` example

Same source pages as above, claim flipped:

```
predicate            = "Python 2 is still officially supported and maintained by the CPython core team"
canonical_url         = "https://www.python.org/doc/sunset-python-2/"
corroborating_url     = "https://devguide.python.org/versions/"
required_signal       = "a statement that Python 2 is still actively supported"
falsifier             = "a statement that Python 2 has reached end-of-life / is no longer supported"
challenge_window_days = 7
```

## `inconclusive` example (forced via an unreachable source)

```
predicate            = "Python 2 has reached end-of-life"
canonical_url         = "https://www.python.org/doc/sunset-python-2/"
corroborating_url     = "https://docs.python.org/3/this-page-does-not-exist-cmcr-test.html"
required_signal       = "a statement that Python 2 is end-of-life"
falsifier             = "a statement that Python 2 is still supported"
challenge_window_days = 7
```

The dead link on `corroborating_url` should make that source's
`page_state == "unreachable"`, which forces `pages_unusable = true` in
`reduce_verdict()` regardless of what the canonical page says. This is
a more reliable way to produce `inconclusive` on demand than trying to
find two real pages that genuinely disagree — true `pages_conflict`
outcomes depend on model interpretation and aren't fully
deterministic to construct by hand.

## Notes

- These examples hit real URLs and real validator LLM calls — no
  mocking. Treat the expected verdicts as predictions to verify, not
  guarantees; page content can change out from under a fixed example
  over time. If a result doesn't match, check `get_case().extract_json`
  first — it shows exactly which source and which boolean a validator
  disagreed on.
- `required_signal` / `falsifier` are free text handed to the
  extraction prompt, not strings matched literally — write them the
  way you'd describe the signal to a person, not as an exact quote to
  search for.

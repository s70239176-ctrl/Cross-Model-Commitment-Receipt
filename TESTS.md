# CMCR (single-instance) — deployment test checklist

Matches the contract you deployed (`cmcr.py`): one commitment per
deployed instance, constructor args `(predicate, canonical_url,
corroborating_url, required_signal, falsifier,
challenge_window_days=7)`. `A`, `B`, `C` are distinct accounts.

`get_case()` is a `@gl.public.view` returning a JSON string — call it
after each step below to confirm state instead of guessing.

---

## 1. `holds` (live pages, real LLM)

Deploy with:
```
predicate            = "Python 2 has reached end-of-life and is no longer maintained by the CPython core team"
canonical_url         = "https://www.python.org/doc/sunset-python-2/"
corroborating_url     = "https://devguide.python.org/versions/"
required_signal       = "a statement that Python 2 is end-of-life / no longer supported"
falsifier             = "a statement that Python 2 is still actively supported or maintained"
challenge_window_days = 7
```

1. `A` (deployer) calls `commit()` with value `100`. → `get_case().status == "committed"`.
2. `B` calls `challenge()` with value `20`. → `status == "challenged"`.
3. Anyone calls `resolve()`.

**Expected:** returns `"holds"`; `get_case().verdict == "holds"`;
`get_case().extract_json.decision == "holds"`; `A`'s balance increases
by `120`; `B` receives nothing. Both source pages genuinely state
Python 2 is EOL, so `has_required=true, has_falsifier=false` on both
is the expected honest extraction — if a validator disagrees, check
`extract_json` for which page it flagged.

---

## 2. `broken` (live pages, real LLM)

Deploy with the **same** `canonical_url`/`corroborating_url` as test 1,
but flip the claim:
```
predicate       = "Python 2 is still officially supported and maintained by the CPython core team"
required_signal = "a statement that Python 2 is still actively supported"
falsifier       = "a statement that Python 2 has reached end-of-life / is no longer supported"
```

1. `A` `commit()` value `100`.
2. `B` `challenge()` value `20`.
3. `resolve()`.

**Expected:** returns `"broken"` (`has_falsifier=true` on both real
pages); `B`'s balance increases by `120`; `A` receives nothing.

---

## 3. `inconclusive` via an unreachable source

Deploy with:
```
predicate         = "Python 2 has reached end-of-life"
canonical_url      = "https://www.python.org/doc/sunset-python-2/"
corroborating_url  = "https://docs.python.org/3/this-page-does-not-exist-cmcr-test.html"
required_signal    = "a statement that Python 2 is end-of-life"
falsifier          = "a statement that Python 2 is still supported"
```

1. `A` `commit()` value `100`.
2. `B` `challenge()` value `20`.
3. `resolve()`.

**Expected:** returns `"inconclusive"` — the 404 on `corroborating_url`
should make that source's `page_state == "unreachable"`, forcing
`pages_unusable = true` in `reduce_verdict()` regardless of what the
canonical page says. `A` refunded `100`, `B` refunded `20`,
`finding` in `extract_json` shows `"pages_unusable": true`. This is
the more reliable way to force `inconclusive` on demand than trying to
find two real pages that disagree — genuine `pages_conflict` cases
depend on model interpretation and aren't fully deterministic to set
up by hand.

---

## 4. Unauthorized commit

1. `A` deploys (any params from test 1). Status is `"open"`.
2. `B` calls `commit()` with value `100`.

**Expected:** reverts with `"only committer"`. `status` stays `"open"`.

---

## 5. Committer cannot challenge their own commitment

1. `A` deploys; `A` `commit()` value `100`. Status `"committed"`.
2. `A` calls `challenge()` with value `20`.

**Expected:** reverts with `"committer cannot challenge"`.

---

## 6. Double challenge rejected

1. `A` deploys; `A` `commit()` value `100`.
2. `B` `challenge()` value `20` → succeeds, status `"challenged"`.
3. `C` calls `challenge()` value `30`.

**Expected:** `C`'s call reverts with `"not committed"` (status is
already `"challenged"`, not `"committed"`). `challenger` stays `B`,
`challenge_stake` stays `20`.

---

## 7. `extend_window` is payer-only and pre-challenge-only

1. `A` deploys with `challenge_window_days = 1`; `A` `commit()` value `100`.
2. `B` calls `extend_window(5)`.

**Expected:** reverts with `"only the committer may extend the window"`.

3. `A` calls `extend_window(5)`.

**Expected:** succeeds; `get_case().window_end` moves ~5 days later.

4. `B` `challenge()` value `20`.
5. `A` calls `extend_window(5)` again.

**Expected:** reverts with `"window can only be extended before the
first challenge"` (status is now `"challenged"`).

---

## 8. `mark_expired` before window close is rejected; unchallenged path

1. `A` deploys with `challenge_window_days = 1`; `A` `commit()` value `100`.
2. Immediately, anyone calls `mark_expired()`.

**Expected:** reverts with `"challenge window has not closed yet"`.

3. Wait until `window_end` has passed (see note below), then call
   `mark_expired()` again.

**Expected:** succeeds; `status == "unchallenged-expired"`,
`challenger` still the zero address.

4. Call `resolve()`.

**Expected:** proceeds with only the two source URLs (no challenger
in this path). If the finding comes back `"broken"`, `A` still
receives their `100` back (see `_payout`'s no-adversary branch in
`resolve()`) — that refund-on-broken-unchallenged behavior is the
thing to specifically check here, since it's the one payoff branch
that differs from the challenged path.

**Note on waiting for expiry:** `challenge_window_days` has a hard
floor of `1` (constructor and `extend_window` both enforce `>= 1`), so
this step genuinely requires real elapsed time in Studio's interactive
UI. If you're scripting this with `gltest` instead, set
`genvm_datetime` in the transaction context to a timestamp past
`window_end` rather than waiting.

---

## 9. Double-resolve rejected

1. Run test 1 or 2 to completion (`resolve()` succeeds once).
2. Call `resolve()` again on the same instance.

**Expected:** reverts with `"not eligible for resolution
(status=holds)"` (or `broken`/`inconclusive`, whichever it settled
on). No second transfer occurs — check balances are unchanged from
before this second call.

---

## 10. Challenge after window closes

1. `A` deploys with `challenge_window_days = 1`; `A` `commit()` value `100`.
2. Wait until `window_end` has passed.
3. `B` calls `challenge()` value `20`.

**Expected:** reverts with `"challenge window has closed"`. Same
real-time/`genvm_datetime` caveat as test 8 applies.

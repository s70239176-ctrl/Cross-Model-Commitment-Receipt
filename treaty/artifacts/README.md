# artifacts/

Record of deployed CMCR instances, written by `scripts/deploy_cmcr.py`
(one JSON file per deployment) or added by hand after a manual Studio
deployment. Configured as gltest's `paths.artifacts` in
`gltest.config.yaml`.

Expected shape per file (`<network>-<slug>.json`):

```json
{
  "network": "studionet",
  "address": "0x...",
  "deployer": "0x...",
  "predicate": "...",
  "canonical_url": "...",
  "corroborating_url": "...",
  "required_signal": "...",
  "falsifier": "...",
  "challenge_window_days": 7
}
```

**Known gap:** `scripts/deploy_cmcr.py` does not currently fill in
`"address"` automatically -- the genlayer-test docs only confirm that
a deployed contract wrapper's `.account` attribute equals the
*deploying* account, not necessarily the contract's own on-chain
address, so the script prints the raw contract object instead of
guessing a wrong attribute name. Fill in `"address"` by hand from
whatever the deploy output / Studio UI shows once you've confirmed
the correct attribute for your installed `genlayer-test` version, then
update the script to do it automatically.

Empty until the first real deployment is recorded here.

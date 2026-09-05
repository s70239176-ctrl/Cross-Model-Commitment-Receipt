# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

from genlayer import *
import json
import datetime

# Address.ZERO is documented but not present on every runner build;
# constructing it explicitly is what actually works here.
_ZERO_ADDRESS = Address("0x0000000000000000000000000000000000000000")


class Contract(gl.Contract):
    committer: Address
    challenger: Address
    predicate: str
    canonical_url: str
    corroborating_url: str
    required_signal: str
    falsifier: str
    status: str
    commit_stake: u256
    challenge_stake: u256
    challenge_window_days: u16
    committed_at: datetime.datetime
    window_end: datetime.datetime
    extract_json: str
    verdict: str

    def __init__(
        self,
        predicate: str,
        canonical_url: str,
        corroborating_url: str,
        required_signal: str,
        falsifier: str,
        challenge_window_days: u16 = 7,
    ):
        if predicate.strip() == "":
            raise Exception("predicate required")
        if not canonical_url.startswith("http"):
            raise Exception("canonical_url must be http(s)")
        if not corroborating_url.startswith("http"):
            raise Exception("corroborating_url must be http(s)")
        if required_signal.strip() == "":
            raise Exception("required_signal required")
        if falsifier.strip() == "":
            raise Exception("falsifier required")
        if challenge_window_days < 1 or challenge_window_days > 90:
            raise Exception("challenge_window_days must be in [1, 90]")

        self.committer = gl.message.sender_address
        self.challenger = _ZERO_ADDRESS
        self.predicate = predicate
        self.canonical_url = canonical_url
        self.corroborating_url = corroborating_url
        self.required_signal = required_signal
        self.falsifier = falsifier
        self.status = "open"
        self.commit_stake = u256(0)
        self.challenge_stake = u256(0)
        self.challenge_window_days = challenge_window_days
        # Sentinel until commit() sets a real timestamp. Every window
        # comparison only ever runs once status != "open", so this is
        # never read as a meaningful date.
        self.committed_at = datetime.datetime(1970, 1, 1)
        self.window_end = datetime.datetime(1970, 1, 1)
        self.extract_json = ""
        self.verdict = ""

    def _pay(self, to: Address, amount: u256) -> None:
        if amount == u256(0):
            return
        gl.get_contract_at(to).emit_transfer(value=amount)

    @gl.public.write.payable
    def commit(self) -> None:
        if gl.message.sender_address != self.committer:
            raise Exception("only committer")
        if self.status != "open":
            raise Exception("not open")
        v = gl.message.value
        if v == u256(0):
            raise Exception("commit requires value")
        now = datetime.datetime.now()
        self.commit_stake = v
        self.status = "committed"
        self.committed_at = now
        self.window_end = now + datetime.timedelta(days=int(self.challenge_window_days))

    @gl.public.write
    def extend_window(self, extra_days: u16) -> None:
        if gl.message.sender_address != self.committer:
            raise Exception("only the committer may extend the window")
        if self.status != "committed":
            raise Exception("window can only be extended before the first challenge")
        if extra_days < 1 or extra_days > 90:
            raise Exception("extra_days must be in [1, 90]")
        self.window_end = self.window_end + datetime.timedelta(days=int(extra_days))

    @gl.public.write.payable
    def challenge(self) -> None:
        if self.status != "committed":
            raise Exception("not committed")
        if datetime.datetime.now() > self.window_end:
            raise Exception("challenge window has closed")
        if gl.message.sender_address == self.committer:
            raise Exception("committer cannot challenge")
        v = gl.message.value
        if v == u256(0):
            raise Exception("challenge requires value")
        self.challenger = gl.message.sender_address
        self.challenge_stake = v
        self.status = "challenged"

    @gl.public.write
    def mark_expired(self) -> None:
        """Permissionless. Pushes an unchallenged commitment past its
        window into 'unchallenged-expired' so resolve() can still
        evaluate it -- silence is not the same as being right, and this
        is what gives an unchallenged commitment a way out of limbo."""
        if self.status != "committed":
            raise Exception("only an unchallenged, committed commitment can expire")
        if datetime.datetime.now() <= self.window_end:
            raise Exception("challenge window has not closed yet")
        self.status = "unchallenged-expired"

    def _extract_source(
        self, url: str, label: str, predicate: str, required_signal: str, falsifier: str
    ) -> dict:
        """Step A -- extraction only, one source at a time. Each
        validator independently fetches this URL and reports what it
        found on THIS page alone. The model never sees the other
        source and is never asked whether the two agree -- that
        comparison is Python's job in resolve(), not the model's."""

        def extract() -> str:
            page = gl.nondet.web.render(url, mode="text")
            prompt = f"""
You extract evidence from a single page. You do not decide who wins money,
and you do not know what any other source says.

PREDICATE:
{predicate}

REQUIRED SIGNAL (must be supported by this page):
{required_signal}

FALSIFIER (if clearly supported by this page, the claim is broken):
{falsifier}

{label} PAGE TEXT:
{page[:8000]}

Return ONLY JSON:
{{
  "has_required": bool,
  "has_falsifier": bool,
  "page_state": "fresh" | "stale" | "unreachable"
}}
page_state is "unreachable" if the page is empty, an error, a block page, or unrelated.
No markdown.
"""
            raw = gl.nondet.exec_prompt(prompt)
            raw = raw.replace("```json", "").replace("```", "").strip()
            data = json.loads(raw)
            out = {
                "has_required": bool(data.get("has_required", False)),
                "has_falsifier": bool(data.get("has_falsifier", False)),
                "page_state": str(data.get("page_state", "unreachable")),
            }
            return json.dumps(out, sort_keys=True)

        principle = f"""
Two extracts of the {label} page are equivalent if has_required, has_falsifier,
and page_state are all identical. Wording does not matter because only these
three fields are compared. Disagree if one extract invents support for the
required signal or falsifier that the page text does not actually contain.
"""
        return json.loads(gl.eq_principle.prompt_comparative(extract, principle))

    @gl.public.write
    def resolve(self) -> str:
        if self.status not in ("challenged", "unchallenged-expired"):
            # No re-resolve, and nothing still "open"/"committed" may
            # be resolved either -- it must first be challenged or
            # expire unchallenged.
            raise Exception("not eligible for resolution (status=" + self.status + ")")

        predicate = self.predicate
        required_signal = self.required_signal
        falsifier = self.falsifier

        # ---- Step A: one independent, live extraction per source ----
        canonical = self._extract_source(
            self.canonical_url, "CANONICAL", predicate, required_signal, falsifier
        )
        corroborating = self._extract_source(
            self.corroborating_url, "CORROBORATING", predicate, required_signal, falsifier
        )

        # ---- Step B: one deterministic reduction, locked by strict_eq ----
        def reduce_verdict(canonical=canonical, corroborating=corroborating) -> str:
            pages_unusable = (
                canonical["page_state"] == "unreachable"
                or corroborating["page_state"] == "unreachable"
            )
            pages_conflict = (
                canonical["has_required"] != corroborating["has_required"]
                or canonical["has_falsifier"] != corroborating["has_falsifier"]
            )

            if pages_unusable or pages_conflict:
                decision = "inconclusive"
            elif canonical["has_falsifier"] or corroborating["has_falsifier"]:
                decision = "broken"
            elif canonical["has_required"] and corroborating["has_required"]:
                decision = "holds"
            else:
                decision = "broken"

            out = {
                "canonical_has_required": canonical["has_required"],
                "corroborating_has_required": corroborating["has_required"],
                "canonical_has_falsifier": canonical["has_falsifier"],
                "corroborating_has_falsifier": corroborating["has_falsifier"],
                "pages_conflict": pages_conflict,
                "pages_unusable": pages_unusable,
                "decision": decision,
            }
            return json.dumps(out, sort_keys=True)

        verdict = json.loads(gl.eq_principle.strict_eq(reduce_verdict))
        self.extract_json = json.dumps(verdict, sort_keys=True)
        decision = verdict["decision"]
        self.verdict = decision

        commit_stake = self.commit_stake
        challenge_stake = self.challenge_stake
        committer = self.committer
        challenger = self.challenger
        has_challenger = challenger != _ZERO_ADDRESS

        if decision == "holds":
            self._pay(committer, commit_stake + challenge_stake)
            self.status = "holds"
        elif decision == "broken":
            if has_challenger:
                self._pay(challenger, commit_stake + challenge_stake)
            else:
                # Unchallenged-expired path: nobody staked against this
                # commitment, so there is nothing principled to slash the
                # stake to. Returning it keeps permissionless resolution
                # from becoming a free griefing tool against committers
                # whose page merely went stale unchallenged; the finding
                # itself (status == "broken") is still recorded above.
                self._pay(committer, commit_stake)
            self.status = "broken"
        else:
            self._pay(committer, commit_stake)
            self._pay(challenger, challenge_stake)
            self.status = "inconclusive"

        return decision

    @gl.public.view
    def get_case(self) -> str:
        return json.dumps(
            {
                "committer": str(self.committer),
                "challenger": str(self.challenger),
                "predicate": self.predicate,
                "canonical_url": self.canonical_url,
                "corroborating_url": self.corroborating_url,
                "required_signal": self.required_signal,
                "falsifier": self.falsifier,
                "status": self.status,
                "commit_stake": str(self.commit_stake),
                "challenge_stake": str(self.challenge_stake),
                "challenge_window_days": str(self.challenge_window_days),
                "committed_at": self.committed_at.isoformat(),
                "window_end": self.window_end.isoformat(),
                "extract_json": self.extract_json,
                "verdict": self.verdict,
            },
            sort_keys=True,
        )
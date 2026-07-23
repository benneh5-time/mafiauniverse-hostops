from __future__ import annotations

import hashlib
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any

import requests
from bs4 import BeautifulSoup
from mafiauniverse import client as mu_api

from .models import PostedReply

log = logging.getLogger(__name__)

TOKEN_FALLBACK_RE = re.compile(
    r'var\s+SECURITYTOKEN\s+=\s+["\']([^"\']+)["\']|name=["\']securitytoken["\']\s+value=["\']([^"\']+)["\']',
    re.I,
)
GAME_ID_RE = re.compile(r"game_id[=\/](\d+)")

# vBulletin's rejection message when a POST carries a stale/invalid security token.
TOKEN_REJECTED_RE = re.compile(r"security token (?:was )?(?:missing|invalid|expired)", re.I)


def token_rejected(text: str | None) -> bool:
    return bool(text and TOKEN_REJECTED_RE.search(text))


class MUClientError(RuntimeError):
    pass


def extract_security_token(html: str) -> str | None:
    token = mu_api.extract_security_token(html or "")
    if token:
        return token
    match = TOKEN_FALLBACK_RE.search(html or "")
    if not match:
        return None
    return next(group for group in match.groups() if group)


def extract_post_id_from_response(response: Any) -> str | None:
    return mu_api.extract_post_id_from_response(response)


_GETQUOTES_CDATA_RE = re.compile(r"<quotes>\s*<!\[CDATA\[(.*?)\]\]>\s*</quotes>", re.S)
_GETQUOTES_PLAIN_RE = re.compile(r"<quotes>(.*?)</quotes>", re.S)


def _unique_suffix() -> str:
    """An invisible, unique BBCode tag appended to a post body.

    MU rejects a post whose body is byte-identical to the previous one, so
    repeated death/ITA announcements would otherwise fail. The tag renders
    with transparent, size-1 text and is not visible in the posted message.
    """
    nonce = f"{time.time_ns():x}{random.randrange(0x10000):04x}"
    return f"\n\n[SIZE=1][COLOR=transparent]{nonce}[/COLOR][/SIZE]"


def parse_post_number(html: str, post_id: int | str) -> str | None:
    """Return the chronological post number for ``post_id`` from thread/post HTML.

    MU renders each post as ``<li ... data-postnumber="N" id="post_<post_id>">``.
    Returns the number as a string, or None if the post is not present.
    """
    if not html or post_id is None:
        return None
    pid = str(post_id)
    # data-postnumber and id may appear in either order on the <li>; match both arrangements.
    pattern = re.compile(
        r"<li\b[^>]*?(?:data-postnumber=\"(\d+)\"[^>]*?id=\"post_" + re.escape(pid) + r"\""
        r"|id=\"post_" + re.escape(pid) + r"\"[^>]*?data-postnumber=\"(\d+)\")",
        re.I,
    )
    match = pattern.search(html)
    if not match:
        return None
    return match.group(1) or match.group(2)


def _parse_getquotes(xml_text: str) -> str:
    """Extract the BBCode payload from a getquotes AJAX response.

    The response wraps the post's BBCode in ``<quotes><![CDATA[...]]></quotes>``.
    Returns the stripped payload, or an empty string if none is present.
    """
    if not xml_text:
        return ""
    match = _GETQUOTES_CDATA_RE.search(xml_text)
    if match:
        return match.group(1).strip()
    match = _GETQUOTES_PLAIN_RE.search(xml_text)
    return match.group(1).strip() if match else ""


@dataclass(slots=True)
class MUClient:
    username: str
    password: str
    base_url: str = "https://www.mafiauniverse.com/forums"
    timeout: int = 30
    session: requests.Session | None = None
    _session: requests.Session = field(init=False, repr=False)
    _security_token: str | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self._session = self.session or requests.Session()
        self._session.headers.update({"User-Agent": "Mozilla/5.0"})

    def _is_logged_in(self) -> bool:
        """True if the session already holds a valid (non-guest) MU login cookie."""
        try:
            cookies = {c.name: c.value for c in self._session.cookies}
        except TypeError:
            # Non-iterable cookie jar (e.g. a bare mock in tests) -> treat as logged out.
            return False
        bb_userid = cookies.get("bb_userid") or cookies.get("bbuserid")
        return bool(bb_userid) and bb_userid != "0"

    def login(self, force: bool = False) -> Any:
        # The session persists cookies across calls, so once authenticated we can
        # reuse the existing login instead of re-POSTing credentials every call.
        if not force and self._is_logged_in():
            return None
        md5_password = hashlib.md5(self.password.encode("utf-8")).hexdigest()
        payload = {
            "do": "login",
            "vb_login_username": self.username,
            "vb_login_md5password": md5_password,
            "vb_login_md5password_utf": md5_password,
            "s": "",
            "securitytoken": "guest",
            "vb_login_password": "",
            "vb_login_password_hint": "Password",
            "cookieuser": "1",
        }
        response = self._session.post(f"{self.base_url}/login.php", data=payload, timeout=self.timeout, allow_redirects=True)
        response.raise_for_status()
        cookies = {c.name: c.value for c in self._session.cookies}
        bb_userid = cookies.get("bb_userid") or cookies.get("bbuserid")
        if bb_userid and bb_userid != "0":
            log.info("MU login succeeded as %s (userid=%s)", self.username, bb_userid)
        else:
            log.warning("MU login failed for %s - cookies: %s - response snippet: %r", self.username, list(cookies.keys()), response.text[200:600])
        # A fresh login invalidates any token issued under the previous session.
        self._security_token = None
        return response

    def refresh_token(self, thread_id: int | str) -> str:
        response = self._session.get(f"{self.base_url}/threads/{thread_id}", timeout=self.timeout)
        response.raise_for_status()
        token = extract_security_token(response.text)
        if not token:
            raise MUClientError("Could not find MU security token in thread HTML")
        self._security_token = token
        return token

    def token(self, thread_id: int | str) -> str:
        # Tokens are per-session, not per-page-load, so reuse the cached one
        # instead of re-downloading the thread page on every call. Callers
        # retry with refresh_token() if MU rejects the cached token.
        if self._security_token and self._security_token != "guest":
            return self._security_token
        return self.refresh_token(thread_id)

    def revive(self, thread_id: int | str, mu_username: str) -> dict:
        self.login()
        try:
            result = mu_api.revive_player(self._session, thread_id, mu_username)
        except ValueError as exc:
            raise MUClientError(f"MU revive returned non-JSON for {mu_username}") from exc
        if not isinstance(result, dict):
            raise MUClientError(f"MU revive returned unexpected response for {mu_username}: {result!r}")
        return result

    def kill(self, thread_id: int | str, mu_username: str) -> dict:
        self.login()
        try:
            result = mu_api.kill_player(self._session, thread_id, mu_username)
        except ValueError as exc:
            raise MUClientError(f"MU kill returned non-JSON for {mu_username}") from exc
        if not isinstance(result, dict):
            raise MUClientError(f"MU kill returned unexpected response for {mu_username}: {result!r}")
        return result

    def post_reply(self, thread_id: int | str, message: str) -> PostedReply:
        self.login()
        token = self.token(thread_id)
        log.debug("post_reply using security token: %r", token)
        if not token or token == "guest":
            raise MUClientError("Security token is 'guest' - session is not authenticated, cannot post reply")
        result = mu_api.post_reply(self._session, thread_id, token, message)
        if token_rejected(result.text):
            # Cached token went stale; a rejected post is never published, so retrying is safe.
            log.info("post_reply: security token rejected, refreshing and retrying once")
            token = self.refresh_token(thread_id)
            result = mu_api.post_reply(self._session, thread_id, token, message)
        if result.status_code >= 400:
            raise MUClientError(f"MU post reply failed with status {result.status_code}")
        return PostedReply(result.text, result.status_code, result.final_url, result.post_id)

    def set_threadmark(self, thread_id: int | str, post_id: str, name: str, postnumber: str = "1") -> Any:
        token = self.token(thread_id)
        response = mu_api.set_threadmark(self._session, thread_id, token, post_id, name, postnumber=postnumber)
        if token_rejected(response.text):
            log.info("set_threadmark: security token rejected, refreshing and retrying once")
            token = self.refresh_token(thread_id)
            response = mu_api.set_threadmark(self._session, thread_id, token, post_id, name, postnumber=postnumber)
        response.raise_for_status()
        return response

    def post_reply_with_threadmark(self, thread_id: int | str, message: str, threadmark_name: str,
                                   unique: bool = True) -> tuple[PostedReply, Any]:
        body = message + _unique_suffix() if unique else message
        reply = self.post_reply(thread_id, body)
        if not reply.post_id:
            raise MUClientError(f"Could not extract post id from posted reply redirect: {reply.final_url}")
        postnumber = parse_post_number(reply.text, reply.post_id) or "1"
        return reply, self.set_threadmark(thread_id, reply.post_id, threadmark_name, postnumber=postnumber)

    def fetch_quote_bbcode(self, thread_id: int | str, post_id: int | str) -> str:
        """Fetch the original BBCode of a post via MU's getquotes AJAX endpoint.

        Returns the post's BBCode already wrapped by MU as ``[QUOTE=...;post_id]...[/QUOTE]``.
        """
        self.login()
        token = self.token(thread_id)
        if not token or token == "guest":
            raise MUClientError("Security token is 'guest' - session is not authenticated, cannot fetch quote")
        response = self._session.post(
            f"{self.base_url}/ajax.php",
            params={"do": "getquotes", "p": str(post_id)},
            data={"do": "getquotes", "p": str(post_id), "securitytoken": token},
            timeout=self.timeout,
        )
        if token_rejected(response.text):
            log.info("fetch_quote_bbcode: security token rejected, refreshing and retrying once")
            token = self.refresh_token(thread_id)
            response = self._session.post(
                f"{self.base_url}/ajax.php",
                params={"do": "getquotes", "p": str(post_id)},
                data={"do": "getquotes", "p": str(post_id), "securitytoken": token},
                timeout=self.timeout,
            )
        if response.status_code >= 400:
            raise MUClientError(f"MU getquotes failed with status {response.status_code} for post {post_id}")
        bbcode = _parse_getquotes(response.text)
        if not bbcode:
            raise MUClientError(f"MU getquotes returned no quote content for post {post_id}")
        return bbcode

    def fetch_thread(self, thread_id: int | str, page: int | str = "lastpost") -> str:
        response = self._session.get(f"{self.base_url}/showthread.php", params={"t": thread_id, "page": page}, timeout=self.timeout)
        response.raise_for_status()
        return response.text

    def fetch_pm_csv(self) -> str:
        """Return the CSV export of all private messages (private.php?do=downloadpm).

        The export includes every folder with full message bodies; callers filter
        to the Inbox. Reading the export does not open individual PMs, so it does
        not change read/unread state on MU.
        """
        self.login()
        response = self._session.get(
            f"{self.base_url}/private.php",
            params={"do": "downloadpm", "dowhat": "csv"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.text

    def fetch_all_thread_posts(self, thread_id: int | str) -> list[dict]:
        """Return every post in a thread, in ascending order, across all pages.

        Delegates to the shared client's pagination. Each dict carries at least
        ``post_id`` and ``author`` (see ``mafiauniverse.client.parse_posts``).
        Requires an authenticated session, so this logs in first.
        """
        self.login()
        return mu_api.fetch_all_posts(thread_id, session=self._session)

    def extract_game_id(self, thread_id: int | str) -> str | None:
        response = self._session.get(f"{self.base_url}/threads/{thread_id}", timeout=self.timeout)
        response.raise_for_status()
        try:
            return mu_api.extract_game_id(response.text)
        except AttributeError:
            match = GAME_ID_RE.search(response.text)
            return match.group(1) if match else None

    def fetch_ita_page_state(self, game_id: int | str) -> tuple[str, list[dict]]:
        """Returns (security_token, [current per-player field dicts]) in page order."""
        response = self._session.get(
            f"{self.base_url}/modbot/manage-game/itas/",
            params={"game_id": game_id},
            timeout=self.timeout,
        )
        response.raise_for_status()
        token = extract_security_token(response.text)
        if not token:
            raise MUClientError(f"Could not find security token on ITA page for game {game_id}")
        soup = BeautifulSoup(response.text, "html.parser")

        def _input_values(name: str) -> list[str]:
            return [str(t.get("value", "0")).strip() for t in soup.find_all("input", {"name": name})]

        def _select_or_input_values(name: str) -> list[str]:
            inputs = soup.find_all("input", {"name": name})
            if inputs:
                return [str(t.get("value", "0")).strip() for t in inputs]
            results = []
            for sel in soup.find_all("select", {"name": name}):
                opt = sel.find("option", selected=True)
                results.append(str(opt.get("value", "0")).strip() if opt else "0")
            return results

        slots = _input_values("slot[]")
        names = _input_values("name[]")
        base_hits = _input_values("ita_base_hit[]")
        immunities = _select_or_input_values("ita_immunity[]")
        vulnerabilities = _select_or_input_values("ita_vulnerability[]")
        shields = _select_or_input_values("ita_shield_status[]")
        bpvs = _select_or_input_values("bpv_status[]")
        boosters = _input_values("ita_booster[]")
        nerfers = _input_values("ita_nerfer[]")
        counts = _input_values("ita_count[]")

        rows = []
        for i, (slot, name) in enumerate(zip(slots, names)):
            if not (slot and name):
                continue
            rows.append({
                "slot": slot,
                "username": name,
                "base_hit": base_hits[i] if i < len(base_hits) else "0",
                "immunity": immunities[i] if i < len(immunities) else "0",
                "vulnerability": vulnerabilities[i] if i < len(vulnerabilities) else "0",
                "shield_status": shields[i] if i < len(shields) else "0",
                "bpv_status": bpvs[i] if i < len(bpvs) else "0",
                "booster": boosters[i] if i < len(boosters) else "0",
                "nerfer": nerfers[i] if i < len(nerfers) else "0",
                "count": counts[i] if i < len(counts) else "1",
            })
        log.debug("ITA page state for game %s: %s", game_id, rows)
        return token, rows

    def push_ita_settings(self, game_id: int | str, settings_by_mu_username: dict[str, dict]) -> int:
        """POST ITA settings to MU. Sheet settings override current page values; unmatched players keep their current values. Returns number of players matched from sheet."""
        self.login()
        token, page_rows = self.fetch_ita_page_state(game_id)
        if not page_rows:
            raise MUClientError(f"No player slots found on ITA page for game {game_id}")
        data: list[tuple[str, str]] = [("s", ""), ("securitytoken", token), ("submit", "1")]
        matched = 0
        for row in page_rows:
            username = row["username"]
            s = settings_by_mu_username.get(username.lower())
            if s is not None:
                matched += 1
                base_hit = str(int(s["base_hit"]))
                immunity = str(int(s["immunity"]))
                booster = str(int(s["booster"]))
                nerfer = str(int(s["nerfer"]))
                count = str(int(s["count"]))
                vulnerability = str(int(s["vulnerability"]))
                shield_status = str(int(s["shield_status"]))
                bpv_status = str(int(s["bpv_status"]))
            else:
                base_hit = row["base_hit"]
                immunity = row["immunity"]
                booster = row["booster"]
                nerfer = row["nerfer"]
                count = row["count"]
                vulnerability = row["vulnerability"]
                shield_status = row["shield_status"]
                bpv_status = row["bpv_status"]
            data.extend([
                ("name[]", username),
                ("slot[]", row["slot"]),
                ("ita_base_hit[]", base_hit),
                ("ita_immunity[]", immunity),
                ("ita_vulnerability[]", vulnerability),
                ("ita_shield_status[]", shield_status),
                ("bpv_status[]", bpv_status),
                ("ita_booster[]", booster),
                ("ita_nerfer[]", nerfer),
                ("ita_count[]", count),
            ])
        log.info("push_ita_settings: sending %d player slots to game %s (token=%r)", len(page_rows), game_id, token[:8] if token else None)
        response = self._session.post(
            f"{self.base_url}/modbot/manage-game/itas/",
            params={"game_id": game_id},
            data=data,
            timeout=self.timeout,
            allow_redirects=True,
        )
        log.info("push_ita_settings response: status=%s url=%s body=%r", response.status_code, response.url, response.text[:300])
        response.raise_for_status()
        return matched

    def fetch_player_statuses(self, game_id: int | str) -> dict[str, bool]:
        response = self._session.get(
            f"{self.base_url}/modbot/manage-game/deaths/",
            params={"game_id": game_id},
            timeout=self.timeout,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        statuses: dict[str, bool] = {}
        for row in soup.select("div.edit_player_row"):
            name_input = row.find("input", {"name": "name[]"})
            alive_select = row.find("select", {"name": "is_alive[]"})
            if not name_input or not alive_select:
                continue
            name = str(name_input.get("value", "")).strip()
            selected = alive_select.find("option", selected=True)
            is_alive = selected and str(selected.get("value", "0")) == "1"
            if name:
                statuses[name.lower()] = bool(is_alive)
        log.debug("MU player statuses for game %s: %s", game_id, statuses)
        return statuses

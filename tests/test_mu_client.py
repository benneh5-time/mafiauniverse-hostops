from __future__ import annotations

import hashlib
from unittest.mock import MagicMock

import pytest

from host_ops.mu_client import MUClient, extract_post_id_from_response, extract_security_token, parse_post_number


class FakeResponse:
    def __init__(self, url="https://mu.test/", text="ok", status_code=200, headers=None, history=None, payload=None):
        self.url = url
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}
        self.history = history or []
        self._payload = payload or {"success": True}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("bad status")

    def json(self):
        return self._payload


def test_login_payload_uses_md5():
    session = MagicMock()
    session.post.return_value = FakeResponse()
    client = MUClient("user", "pass", session=session)
    client.login()
    data = session.post.call_args.kwargs["data"]
    assert data["vb_login_md5password"] == hashlib.md5(b"pass").hexdigest()
    assert data["securitytoken"] == "guest"


def test_login_skipped_when_already_authenticated():
    import requests

    session = requests.Session()
    session.cookies.set("bb_userid", "4242")
    session.post = MagicMock(return_value=FakeResponse())
    client = MUClient("user", "pass", session=session)

    client.login()  # cookie already present -> no login POST
    session.post.assert_not_called()

    client.login(force=True)  # force re-issues the login POST
    session.post.assert_called_once()


def test_login_runs_when_userid_is_guest_zero():
    import requests

    session = requests.Session()
    session.cookies.set("bb_userid", "0")
    session.post = MagicMock(return_value=FakeResponse())
    client = MUClient("user", "pass", session=session)

    client.login()  # userid "0" is not authenticated -> must log in
    session.post.assert_called_once()


def test_extract_security_token_script_and_input():
    assert extract_security_token('var SECURITYTOKEN = "abc";') == "abc"
    assert extract_security_token('<input name="securitytoken" value="def">') == "def"


def test_refresh_token_missing_raises():
    session = MagicMock()
    session.get.return_value = FakeResponse(text="no token")
    client = MUClient("u", "p", session=session)
    with pytest.raises(RuntimeError):
        client.refresh_token(123)


def test_kill_api_get_params():
    session = MagicMock()
    session.get.return_value = FakeResponse(payload={"success": True})
    client = MUClient("u", "p", session=session)
    assert client.kill(123, "Alice") == {"success": True}
    assert session.get.call_args.args[0] == "https://www.mafiauniverse.com/forums/modbot/api/death/?do=kill&threadid=123&username=Alice"


def test_post_id_from_final_url_and_history_location():
    assert extract_post_id_from_response(FakeResponse(url="https://mu/threads/1?p=10893315#post10893315")) == "10893315"
    hist = FakeResponse(headers={"Location": "https://mu/threads/1?p=55#post55"})
    assert extract_post_id_from_response(FakeResponse(history=[hist])) == "55"


def test_post_id_conflict_or_missing_is_none():
    hist = FakeResponse(url="https://mu/threads/1?p=1")
    assert extract_post_id_from_response(FakeResponse(url="https://mu/threads/1#post2", history=[hist])) is None
    assert extract_post_id_from_response(FakeResponse(url="https://mu/threads/1")) is None


def test_threadmark_payload_uses_postnumber_one():
    session = MagicMock()
    session.get.return_value = FakeResponse(text='var SECURITYTOKEN = "tok";')
    session.post.return_value = FakeResponse()
    client = MUClient("u", "p", session=session)
    client.set_threadmark(123, "999", "Death: Alice")
    data = session.post.call_args.kwargs["data"]
    assert data["do"] == "set_threadmark"
    assert data["postid"] == "999"
    assert data["postnumber"] == "1"


GETQUOTES_SAMPLE = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    "<quotes><![CDATA[[QUOTE=MU Anniversary 2026;11042484][CENTER][TITLE]"
    "[B]A shot rings out![/B][/TITLE][/CENTER]\n\ntest?[/QUOTE]\n\n]]></quotes>"
)


def test_fetch_quote_bbcode_posts_getquotes_with_token_and_post_id():
    session = MagicMock()
    session.get.return_value = FakeResponse(text='var SECURITYTOKEN = "tok";')
    session.post.return_value = FakeResponse(text=GETQUOTES_SAMPLE)
    client = MUClient("u", "p", session=session)

    bbcode = client.fetch_quote_bbcode(123, "11042484")

    # request shape
    url = session.post.call_args.args[0]
    data = session.post.call_args.kwargs["data"]
    assert url == "https://www.mafiauniverse.com/forums/ajax.php"
    assert data["do"] == "getquotes"
    assert data["p"] == "11042484"
    assert data["securitytoken"] == "tok"
    # parsed BBCode is the CDATA payload, wrapped by MU, stripped of surrounding whitespace
    assert bbcode.startswith("[QUOTE=MU Anniversary 2026;11042484]")
    assert bbcode.endswith("[/QUOTE]")
    assert "A shot rings out!" in bbcode


def test_fetch_quote_bbcode_empty_response_raises():
    session = MagicMock()
    session.get.return_value = FakeResponse(text='var SECURITYTOKEN = "tok";')
    session.post.return_value = FakeResponse(text="<quotes></quotes>")
    client = MUClient("u", "p", session=session)
    with pytest.raises(Exception):
        client.fetch_quote_bbcode(123, "11042484")


# Real MU postbit markup carries the chronological number in data-postnumber on the <li>.
POSTBIT_SAMPLE = (
    '<li class="postbitlegacy postbitim postcontainer old" data-postnumber="1" id="post_11042392">first</li>'
    '<li class="postbitlegacy postbitim postcontainer old" data-postnumber="7" id="post_11042417">seventh</li>'
    '<li class="postbitlegacy postbitim postcontainer old" data-postnumber="30" id="post_11065447">thirtieth</li>'
)


def test_parse_post_number_finds_data_postnumber_for_post_id():
    assert parse_post_number(POSTBIT_SAMPLE, "11042417") == "7"
    assert parse_post_number(POSTBIT_SAMPLE, "11065447") == "30"


def test_parse_post_number_missing_post_returns_none():
    assert parse_post_number(POSTBIT_SAMPLE, "99999999") is None
    assert parse_post_number("", "11042417") is None


def test_set_threadmark_uses_provided_postnumber():
    session = MagicMock()
    session.get.return_value = FakeResponse(text='var SECURITYTOKEN = "tok";')
    session.post.return_value = FakeResponse()
    client = MUClient("u", "p", session=session)
    client.set_threadmark(123, "11042417", "In-Thread Attack: X hit Y", postnumber="7")
    data = session.post.call_args.kwargs["data"]
    assert data["postnumber"] == "7"


def test_post_reply_with_threadmark_parses_postnumber_from_reply():
    session = MagicMock()
    session.get.return_value = FakeResponse(text='var SECURITYTOKEN = "tok";')
    # post_reply returns the thread page whose text carries the new post's data-postnumber
    reply_page = FakeResponse(
        url="https://mu/threads/61980?p=11042417#post11042417",
        text=POSTBIT_SAMPLE,
    )
    session.post.return_value = reply_page
    client = MUClient("u", "p", session=session)
    _reply, _tm = client.post_reply_with_threadmark(61980, "message body", "In-Thread Attack: X hit Y")
    # the final POST (threadmark) must carry postnumber 7 for post_id 11042417
    threadmark_data = session.post.call_args.kwargs["data"]
    assert threadmark_data["do"] == "set_threadmark"
    assert threadmark_data["postid"] == "11042417"
    assert threadmark_data["postnumber"] == "7"


def _posted_body(session):
    """The message body sent by the post_reply POST call (the one carrying 'message')."""
    for call in session.post.call_args_list:
        data = call.kwargs.get("data") or {}
        if "message" in data:
            return data["message"]
    raise AssertionError("no post_reply call with a message body was made")


def test_post_reply_with_threadmark_appends_invisible_nonce_by_default():
    session = MagicMock()
    session.get.return_value = FakeResponse(text='var SECURITYTOKEN = "tok";')
    session.post.return_value = FakeResponse(
        url="https://mu/threads/61980?p=11042417#post11042417", text=POSTBIT_SAMPLE)
    client = MUClient("u", "p", session=session)
    client.post_reply_with_threadmark(61980, "the death post", "A shot rings out! X is dead")
    body = _posted_body(session)
    assert body.startswith("the death post")
    assert "[SIZE=1][COLOR=transparent]" in body
    assert "[/COLOR][/SIZE]" in body


def test_post_reply_with_threadmark_nonce_differs_between_identical_posts():
    session = MagicMock()
    session.get.return_value = FakeResponse(text='var SECURITYTOKEN = "tok";')
    session.post.return_value = FakeResponse(
        url="https://mu/threads/61980?p=11042417#post11042417", text=POSTBIT_SAMPLE)
    client = MUClient("u", "p", session=session)

    client.post_reply_with_threadmark(61980, "same body", "same mark")
    first_body = _posted_body(session)
    session.post.reset_mock()
    client.post_reply_with_threadmark(61980, "same body", "same mark")
    second_body = _posted_body(session)

    assert first_body != second_body


def test_post_reply_with_threadmark_can_disable_nonce():
    session = MagicMock()
    session.get.return_value = FakeResponse(text='var SECURITYTOKEN = "tok";')
    session.post.return_value = FakeResponse(
        url="https://mu/threads/61980?p=11042417#post11042417", text=POSTBIT_SAMPLE)
    client = MUClient("u", "p", session=session)
    client.post_reply_with_threadmark(61980, "exact body", "mark", unique=False)
    assert _posted_body(session) == "exact body"

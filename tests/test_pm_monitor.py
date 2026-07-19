from __future__ import annotations

from host_ops.pm_monitor import (
    bbcode_to_markdown,
    parse_pm_detail,
    parse_unread_pmids,
)

# Trimmed from a real private.php?folderid=0 inbox page: two unread, one read.
INBOX_HTML = """
<ol class="pmlist">
    <li class="blockrow pmbit" id="pm_775494">
        <img src="images/metro/blue/statusicon/pm_old.png" class="threadicon" alt="" />
        <span>
            <a href="private.php?do=showpm&amp;pmid=775494" class="title">Read one</a>
        </span>
        <ol class="commalist"><li><a class="username understate">Mafia Host</a></li></ol>
    </li>
    <li class="blockrow pmbit" id="pm_774414">
        <img src="images/metro/blue/statusicon/pm_new.png" class="threadicon" alt="" />
        <span class="unread">
            <a href="private.php?do=showpm&amp;pmid=774414" class="title">Night 4 Results</a>
        </span>
        <ol class="commalist"><li><a class="username understate">Mafia Host</a></li></ol>
    </li>
    <li class="blockrow pmbit" id="pm_774410">
        <img src="images/metro/blue/statusicon/pm_new.png" class="threadicon" alt="" />
        <span class="unread">
            <a href="private.php?do=showpm&amp;pmid=774410" class="title">Night 3 Results</a>
        </span>
        <ol class="commalist"><li><a class="username understate">Mafia Host</a></li></ol>
    </li>
</ol>
"""

# Trimmed from a real private.php?do=showpm&pmid=774414 page.
SHOWPM_HTML = """
<div id="showpm"><ol>
<li class="postbitlegacy postbitim postcontainer postby-11 new host-post" id="post_">
  <div class="postdetails"><div class="userinfo"><div class="username_container">
    <div class="popupmenu memberaction">
      <a class="username offline popupctrl" href="members/11-Mafia-Host">
        <strong><span class="modbot">Mafia Host</span></strong></a>
    </div>
  </div></div>
  <div class="postbody"><div class="postrow">
    <h2 class="title icon">Night 4 Results [SHOOT THE LUTE IS ONLINE - [shootthelute10 game]]</h2>
    <div class="content"><div id="post_message_">
      <blockquote class="postcontent restore ">rendered here</blockquote>
    </div></div>
  </div></div>
  </div>
</li>
</ol>
<textarea id="vB_Editor_QR_editor" name="message" rows="8" cols="60">[QUOTE=Mafia Host][CENTER][TITLE]Night 4 Results for SHOOT THE LUTE IS ONLINE[/TITLE][/CENTER]

[BOX=Host Info][B]olitest08[/B] used a Factional Kill on [B]olitest06[/B] and succeeded.[/BOX][/QUOTE]
</textarea>
</div>
"""


def test_parse_unread_pmids_returns_only_unread():
    assert parse_unread_pmids(INBOX_HTML) == [774414, 774410]


def test_parse_unread_pmids_empty_when_none_unread():
    html = '<ol class="pmlist"><li class="blockrow pmbit" id="pm_1">' \
           '<span><a class="title">read</a></span></li></ol>'
    assert parse_unread_pmids(html) == []


def test_parse_pm_detail_author():
    assert parse_pm_detail(SHOWPM_HTML)["author"] == "Mafia Host"


def test_parse_pm_detail_subject():
    detail = parse_pm_detail(SHOWPM_HTML)
    assert detail["subject"] == "Night 4 Results [SHOOT THE LUTE IS ONLINE - [shootthelute10 game]]"


def test_parse_pm_detail_strips_outer_quote_wrapper():
    bbcode = parse_pm_detail(SHOWPM_HTML)["bbcode"]
    assert not bbcode.startswith("[QUOTE")
    assert "[/QUOTE]" not in bbcode
    assert "[B]olitest08[/B]" in bbcode


def test_bbcode_bold():
    assert bbcode_to_markdown("[B]hi[/B]") == "**hi**"


def test_bbcode_title_becomes_bold_header():
    assert bbcode_to_markdown("[TITLE]Results[/TITLE]").strip() == "**Results**"


def test_bbcode_box_label_and_contents():
    out = bbcode_to_markdown("[BOX=Host Info]body text[/BOX]")
    assert "**Host Info**" in out
    assert "body text" in out


def test_bbcode_unknown_tag_stripped_contents_kept():
    assert bbcode_to_markdown("[CENTER]middle[/CENTER]").strip() == "middle"

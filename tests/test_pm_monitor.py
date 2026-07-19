from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from host_ops.pm_monitor import (
    PACIFIC,
    bbcode_to_text,
    format_pm_message,
    parse_pm_csv,
)

# A downloadpm CSV with one Sent row (ignored) and two Inbox rows. Bodies contain
# commas, doubled-quote escaping, and embedded newlines — must be CSV-parsed.
CSV_TEXT = (
    'Date,Folder,Title,From,To,Message\n'
    '"2026-07-18 18:52","Sent Items","Role PM","MU Anniversary 2026","asdf",'
    '"[QUOTE][TITLE]Role[/TITLE]\n\nYou are [B][COLOR=""#008000""]a guy[/COLOR][/B]."\n'
    '"2026-07-19 09:15","Inbox","Night 4 Results","Mafia Host","benneh",'
    '"[QUOTE][B]alice[/B] killed [B]bob[/B].[/QUOTE]"\n'
    '"2026-07-19 10:30","Inbox","Voting Form","Lissa","benneh","Please vote, here."\n'
)


def test_parse_pm_csv_filters_to_inbox_only():
    rows = parse_pm_csv(CSV_TEXT)
    assert [r["title"] for r in rows] == ["Night 4 Results", "Voting Form"]


def test_parse_pm_csv_fields():
    row = parse_pm_csv(CSV_TEXT)[0]
    assert row["sender"] == "Mafia Host"
    assert row["title"] == "Night 4 Results"
    assert "[B]alice[/B]" in row["bbcode"]


def test_parse_pm_csv_body_with_embedded_comma_intact():
    row = parse_pm_csv(CSV_TEXT)[1]
    assert row["bbcode"] == "Please vote, here."


def test_parse_pm_csv_date_is_pacific_aware():
    row = parse_pm_csv(CSV_TEXT)[0]
    assert row["date"] == datetime(2026, 7, 19, 9, 15, tzinfo=PACIFIC)
    # July → PDT → UTC-7
    assert row["date"].utcoffset().total_seconds() == -7 * 3600


def test_parse_pm_csv_cutoff_comparison_across_timezones():
    # A cutoff expressed in UTC must compare correctly against Pacific CSV dates.
    rows = parse_pm_csv(CSV_TEXT)
    # 2026-07-19 09:15 PDT == 16:15 UTC. Cutoff at 16:20 UTC should exclude it.
    cutoff = datetime(2026, 7, 19, 16, 20, tzinfo=ZoneInfo("UTC"))
    after = [r for r in rows if r["date"] > cutoff]
    assert [r["title"] for r in after] == ["Voting Form"]


def test_parse_pm_csv_empty():
    assert parse_pm_csv("") == []
    assert parse_pm_csv("Date,Folder,Title,From,To,Message\n") == []


def test_bbcode_to_text_strips_all_tags():
    # Plain text for a code block: no markdown, just the words.
    assert bbcode_to_text("[B]hi[/B]") == "hi"
    assert bbcode_to_text("[TITLE]Results[/TITLE]").strip() == "Results"
    assert bbcode_to_text("[BOX=Host Info]body text[/BOX]").strip() == "Host Info\nbody text"


def test_bbcode_to_text_unknown_tag_stripped_contents_kept():
    assert bbcode_to_text("[CENTER]middle[/CENTER]").strip() == "middle"


def test_bbcode_to_text_drops_quote_block_and_contents():
    assert bbcode_to_text("[QUOTE]old convo here[/QUOTE]") == ""


def test_bbcode_to_text_keeps_text_outside_quote():
    text = "[QUOTE=Alice]earlier stuff[/QUOTE]This is my new reply."
    assert bbcode_to_text(text) == "This is my new reply."


def test_bbcode_to_text_drops_nested_quote_keeps_outer_text():
    text = "New line.\n[QUOTE][QUOTE=Bob]deep[/QUOTE]mid[/QUOTE]\nAnother new line."
    out = bbcode_to_text(text)
    assert "deep" not in out and "mid" not in out
    assert "New line." in out and "Another new line." in out


def test_format_pm_message_layout():
    out = format_pm_message("Mafia Host", "Night 4 Results", "[B]alice[/B] won.")
    assert out.startswith("**From:** Mafia Host - **Subject:** Night 4 Results")
    assert "```" in out
    assert "alice won." in out
    assert "**alice**" not in out  # body is plain text, no markdown


def test_format_pm_message_empty_body_omits_code_block():
    out = format_pm_message("Lissa", "Re: hi", "[QUOTE]only old quoted text[/QUOTE]")
    assert out.startswith("**From:** Lissa - **Subject:** Re: hi")
    assert "```" not in out  # nothing to show, no empty code block

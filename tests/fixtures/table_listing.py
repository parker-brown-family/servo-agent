"""A listing page laid out the way Hacker News serves its front page (issue #13).

Rows sit directly inside <table> with no <tbody>, as HN's HTML has them; a
browser inserts the <tbody> while parsing, a plain download does not. Built in
code rather than saved from HN, so the test carries no third-party content.
"""
from __future__ import annotations

STORIES = 30


def listing_html(stories: int = STORIES) -> str:
    rows = []
    for i in range(1, stories + 1):
        rows.append(
            f'<tr class="athing submission" id="{i}">'
            f'<td align="right" valign="top" class="title"><span class="rank">{i}.</span></td>'
            f'<td valign="top" class="votelinks"><center>'
            f'<a id="up_{i}" href="vote?id={i}&amp;how=up">'
            f'<div class="votearrow" title="upvote"></div></a></center></td>'
            f'<td class="title"><span class="titleline"><a href="https://example.org/story/{i}">'
            f"Story number {i} about rendering engines</a>"
            f'<span class="sitebit comhead"> (<a href="from?site=example.org">'
            f'<span class="sitestr">example.org</span></a>)</span></span></td></tr>'
            f'<tr><td colspan="2"></td><td class="subtext"><span class="subline">'
            f'<span class="score" id="score_{i}">{100 + i} points</span> by '
            f'<a href="user?id=user{i}" class="hnuser">user{i}</a> '
            f'<span class="age" title="2026-10-22T10:00:00">'
            f'<a href="item?id={i}">{i} hours ago</a></span> | '
            f'<a href="item?id={i}">{i * 3}&nbsp;comments</a></span></td></tr>'
            f'<tr class="spacer" style="height:5px"></tr>'
        )
    return (
        "<html lang=\"en\"><head><title>Listing</title></head><body><center>"
        '<table id="hnmain" border="0" cellpadding="0" cellspacing="0" width="85%">'
        '<tr><td><table border="0" cellpadding="0" cellspacing="0" width="100%"><tr>'
        '<td><span class="pagetop"><b class="hnname"><a href="news">Listing</a></b> '
        '<a href="newest">new</a> | <a href="front">past</a></span></td></tr></table></td></tr>'
        '<tr id="bigbox"><td><table border="0" cellpadding="0" cellspacing="0">'
        + "".join(rows)
        + '<tr><td colspan="2"></td><td class="title"><a href="?p=2" class="morelink">More</a>'
        "</td></tr></table></td></tr></table></center></body></html>"
    )

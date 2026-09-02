import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from highland.robots import Robots

CARMAX = """
User-agent: *
Disallow: /car/*
Disallow: /mycarmax/sign-in*
Disallow: /*stocknumber=*

User-agent: trovitBot
Disallow: /
"""


def test_wildcards():
    r = Robots.parse(CARMAX)
    assert not r.can_fetch("/car/12345")
    assert r.can_fetch("/cars/api/search/run?uri=%2Fcars%2Ftesla")
    assert not r.can_fetch("/cars/tesla?stocknumber=1")
    assert r.can_fetch("/cars/tesla/model-3")
    assert not r.can_fetch("/", agent="trovitBot")


def test_allow_beats_disallow_on_tie_and_longest_wins():
    r = Robots.parse("User-agent: *\nDisallow: /shopping/\nAllow: /shopping/results\n")
    assert r.can_fetch("/shopping/results?x=1")
    assert not r.can_fetch("/shopping/other")


def test_crawl_delay_and_end_anchor():
    r = Robots.parse("User-agent: *\nCrawl-delay: 2\nDisallow: /*.json$\n")
    assert r.crawl_delay() == 2
    assert not r.can_fetch("/api/data.json")
    assert r.can_fetch("/api/data.json?x=1")


def test_empty_disallow_allows_all():
    r = Robots.parse("User-agent: *\nDisallow:\n")
    assert r.can_fetch("/anything")


def test_repeated_star_groups_are_merged():
    txt = "User-agent: *\nDisallow: /a\n\nUser-agent: *\nDisallow: /b\nCrawl-delay: 3\n"
    r = Robots.parse(txt)
    assert not r.can_fetch("/a/x") and not r.can_fetch("/b") and r.can_fetch("/c")
    assert r.crawl_delay() == 3

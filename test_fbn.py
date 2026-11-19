from core.cookie_manager import parse_facebook_cookies
from core.fbn_scraper import (
    extract_group_identifier,
    extract_post_id_from_url,
    extract_post_id_from_ft,
    build_canonical_post_url,
    build_author_group_url,
)
from core.notifier import clean_html_content, parse_apprise_url

def test_all():
    # Header format
    raw1 = "c_user=1000987654321; xs=2%3Aabc123xyz%3A2; datr=abc;"
    c1, uid1, err1 = parse_facebook_cookies(raw1)
    assert uid1 == "1000987654321"
    assert err1 is None
    assert len(c1) == 3

    # JSON format
    raw2 = '[{"name": "c_user", "value": "100011223344"}, {"name": "xs", "value": "2%3Atest"}]'
    c2, uid2, err2 = parse_facebook_cookies(raw2)
    assert uid2 == "100011223344"
    assert err2 is None
    assert len(c2) == 2

    # Group URL extractor
    assert extract_group_identifier("https://www.facebook.com/groups/laptrinhvn") == "laptrinhvn"
    assert extract_group_identifier("https://www.facebook.com/groups/123456789/?ref=share") == "123456789"
    assert extract_group_identifier("99887766") == "99887766"

    # Apprise URL parser
    bot, chat = parse_apprise_url("tgram://123456:ABC/987654")
    assert bot == "123456:ABC"
    assert chat == "987654"

    # Clean HTML
    assert clean_html_content("<b>Hello & Welcome</b>") == "Hello &amp; Welcome"

    # Post ID extraction from diverse URL formats
    test_urls = [
        "https://www.facebook.com/groups/524659961313411/posts/1685472895232106/",
        "/groups/524659961313411/posts/1685472895232106/?comment_id=123",
        "/groups/524659961313411/permalink/1685472895232106/",
        "/story.php?story_fbid=1685472895232106&id=524659961313411",
        "https://m.facebook.com/story.php?story_fbid=1685472895232106&id=524659961313411",
        "/permalink.php?story_fbid=1685472895232106&id=524659961313411",
        "/groups/524659961313411?view=permalink&id=1685472895232106",
        "/groups/524659961313411/multi_permalinks=1685472895232106",
        "https://www.facebook.com/photo.php?fbid=999999&set=gm.1685472895232106",
        "https://www.facebook.com/photo.php?fbid=999999&set=pcb.1685472895232106",
        "/groups/524659961313411/user/1000123456/story/1685472895232106",
    ]
    for u in test_urls:
        pid = extract_post_id_from_url(u)
        assert pid == "1685472895232106", f"Failed to extract post ID from: {u}"

    # Post ID extraction from data-ft attributes
    ft_samples = [
        '{"mf_story_key":"1685472895232106","top_level_post_id":"1685472895232106"}',
        '{"top_level_post_id": 1685472895232106}',
        '{"story_fbid": [1685472895232106]}',
        '{"story_fbids": ["1685472895232106"]}',
        '{"tl_objid": "1685472895232106"}',
    ]
    for ft in ft_samples:
        pid = extract_post_id_from_ft(ft)
        assert pid == "1685472895232106", f"Failed to extract post ID from ft: {ft}"

    # Canonical post URL generation
    canonical1 = build_canonical_post_url("524659961313411", "1685472895232106")
    assert canonical1 == "https://www.facebook.com/groups/524659961313411/posts/1685472895232106/"

    canonical2 = build_canonical_post_url(
        "524659961313411",
        None,
        "/story.php?story_fbid=1685472895232106&id=524659961313411",
    )
    assert canonical2 == "https://www.facebook.com/groups/524659961313411/posts/1685472895232106/"

    # Author group URL generation
    author_url1 = build_author_group_url("524659961313411", "100012345678", "Nguyễn Văn A")
    assert author_url1 == "https://www.facebook.com/groups/524659961313411/user/100012345678/"

    author_url2 = build_author_group_url(
        "524659961313411",
        None,
        "Nguyễn Văn A",
        author_href="/groups/524659961313411/user/100098765432/",
    )
    assert author_url2 == "https://www.facebook.com/groups/524659961313411/user/100098765432/"

    author_url3 = build_author_group_url("524659961313411", None, "Trần Văn B")
    assert "search/?q=" in author_url3 and "524659961313411" in author_url3

    print("✓ All fbn unit tests passed successfully!")

if __name__ == "__main__":
    test_all()

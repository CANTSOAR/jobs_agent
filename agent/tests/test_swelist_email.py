from inbox.parser import classify_message, parse_swelist_html, parse_swelist_text


def test_parse_plain_text_bounds_and_deduplicates():
    body = """Intro: not a job
Here is your daily update (9/8) of tech internships from swelist:
Coretek Services: AI & Automation Development Intern
Cox: Product Management Intern - Summer 2027
Cox: Product Management Intern - Summer 2027
See more details by visiting the repo: Summer2027-Internships
Footer: still not a job
"""

    listings = parse_swelist_text(body)

    assert [(item.company, item.title, item.url) for item in listings] == [
        ("Coretek Services", "AI & Automation Development Intern", None),
        ("Cox", "Product Management Intern - Summer 2027", None),
    ]


def test_parse_html_preserves_application_links_and_unicode():
    html = """
      <p>Here is your daily update of tech internships from SWEList:</p>
      <a href="https://example.test/jobs/123?utm_source=email">Apple: GPU Intern – Multiple Teams</a>
      <a href="https://example.test/jobs/123?utm_source=email">Apple: GPU Intern – Multiple Teams</a>
      <p>See more details by visiting the repo</p>
    """

    listings = parse_swelist_html(html)

    assert len(listings) == 1
    assert listings[0].company == "Apple"
    assert listings[0].title == "GPU Intern – Multiple Teams"
    assert listings[0].url == "https://example.test/jobs/123?utm_source=email"


def test_classification_prefers_verified_sender_shape():
    assert classify_message("SWE List <noreply@swelist.com>", "Daily update", "") == "swelist_digest"
    assert classify_message("spoof@example.com", "SWEList daily update", "") == "unknown"
    assert classify_message("careers@example.com", "Application received", "Thanks") == "application_confirmation"

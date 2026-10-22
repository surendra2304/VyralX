import httpx
from app.services.mixkit import MIXKIT_SEARCH_URL, DEFAULT_HEADERS

with httpx.Client(timeout=10.0, follow_redirects=True, headers=DEFAULT_HEADERS) as client:
    for term in ['human-dna', 'dna', 'laboratory', 'microscope', 'cells']:
        url1 = f"{MIXKIT_SEARCH_URL}{term}/"
        url2 = f"{MIXKIT_SEARCH_URL}?q={term}"
        for u in [url1, url2]:
            resp = client.get(u)
            print(f"{u:45s} -> {str(resp.url):45s} (discover: {'/discover/' in str(resp.url)})")

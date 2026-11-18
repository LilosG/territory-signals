import sys; sys.path.insert(0, "recon/scripts")
from _http import get
for u in ["https://data.sandiego.gov/robots.txt","https://data.sandiego.gov/datasets/stro-licenses/","https://data.sandiego.gov/datasets/development-permits/","https://data.sandiego.gov/terms-of-use/"]:
    r = get(u); print("=====", u, r.status_code, len(r.text)); 
    import re
    if "robots" in u: print(r.text[:800])
    else:
        print(re.sub(r"\s+"," ",re.sub(r"<script.*?</script>|<style.*?</style>","",r.text,flags=re.S))[:200])
        for m in sorted(set(re.findall(r'href="([^"]+\.(?:csv|json|geojson|zip|xlsx)[^"]*)"', r.text))): print("LINK", m)

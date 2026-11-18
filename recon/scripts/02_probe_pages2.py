import sys,re; sys.path.insert(0, "recon/scripts")
from _http import get
def txt(h): return re.sub(r"\s+"," ",re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>"," ",h,flags=re.S))
for u in ["https://data.sandiego.gov/datasets/stro-licenses/","https://data.sandiego.gov/datasets/development-permits/"]:
    t=txt(get(u).text); i=t.find("Description"); print("=====",u); print(t[:3500]); print()
r=get("https://data.sandiego.gov/"); 
for m in sorted(set(re.findall(r'href="([^"]*(?:terms|license|about|policy)[^"]*)"', r.text, re.I))): print("HOMELINK",m)

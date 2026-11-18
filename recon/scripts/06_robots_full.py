import sys; sys.path.insert(0,"recon/scripts")
from _http import get
for h in ["www.sdcourt.ca.gov","www.legacy.com","www.sandiegouniontribune.com"]:
    t=get(f"https://{h}/robots.txt").text
    open(f"recon/raw/robots_{h}.txt","w").write(t)
    print("=====",h,len(t))
    lines=[l for l in t.splitlines() if not l.startswith("# ") or "Content-Signal" in l or "prohibit" in l.lower()]
    print("\n".join(lines)[:2500])

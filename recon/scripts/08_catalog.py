import sys,json,re; sys.path.insert(0,"recon/scripts")
from _http import get
r=get("https://raw.githubusercontent.com/COSD-PANDA/data-inventory/refs/heads/master/data.json",timeout=120)
open("recon/raw/cosd_catalog.json","w").write(r.text)
cat=r.json()
print(len(cat["dataset"]))
kw=re.compile(r"parcel|zoning|address points|transit|stop|community plan|planning area|council|zip|fire|land use|sb ?9|sb ?79|overlay",re.I)
for d in cat["dataset"]:
    if kw.search(d["title"]):
        print("-",d["title"],"|",d.get("accrualPeriodicity"),"|",d.get("modified"))
        for x in d.get("distribution",[]):
            u=x.get("downloadURL") or x.get("accessURL")
            if u and re.search(r"\.(csv|geojson|zip|json)$",u): print("     ",u)

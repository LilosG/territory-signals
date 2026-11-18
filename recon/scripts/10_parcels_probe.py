import sys,json,re; sys.path.insert(0,"recon/scripts")
from _http import get
B="https://geo.sandag.org/server/rest/directories/downloads/"
r=get(B+"Parcels.csv",headers={"Range":"bytes=0-6000"},stream=False)
print(r.status_code, r.headers.get("content-range")); 
lines=r.text.splitlines(); print(lines[0]); print(lines[1][:600]); open("recon/raw/parcels_head.txt","w").write("\n".join(lines[:4]))
r=get("https://geo.sandag.org/server/rest/services?f=pjson"); print(r.status_code)
try:
    j=r.json(); print([s["name"]+":"+s["type"] for s in j.get("services",[])][:80], j.get("folders"))
except Exception as e: print(r.text[:300])

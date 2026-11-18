import sys,os; sys.path.insert(0,"recon/scripts")
from _http import get
B="https://geo.sandag.org/server/rest/directories/downloads/"
for n in ["Community_Plan_SD.geojson","Zoning_Base_SD.geojson","Transit_Stops_GTFS.geojson","Parcels.csv"]:
    p="recon/raw/"+n
    if os.path.exists(p): continue
    r=get(B+n,stream=True,timeout=900); r.raise_for_status()
    with open(p+".part","wb") as f:
        for c in r.iter_content(1<<20): f.write(c)
    os.rename(p+".part",p); print("done",n,os.path.getsize(p),flush=True)

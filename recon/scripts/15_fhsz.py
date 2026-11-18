import sys,json; sys.path.insert(0,"recon/scripts")
from _http import get
h="services.gis.ca.gov"
r=get(f"https://{h}/robots.txt"); print("robots",r.status_code,r.text[:300])
base=f"https://{h}/arcgis/rest/services/Environment/Fire_Severity_Zones/MapServer"
r=get(base+"?f=pjson"); print(r.status_code, r.text[:200])
try:
    j=r.json(); print([ (l["id"],l["name"]) for l in j.get("layers",[])]); print(j.get("serviceDescription","")[:500]); print(j.get("copyrightText"))
except Exception as e: print("ERR",e)

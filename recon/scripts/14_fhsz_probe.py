import sys,json; sys.path.insert(0,"recon/scripts")
from _http import get
for u in ["https://geo.sandag.org/server/rest/services/Hosted/Fire_Hazard_Severity_Zones/FeatureServer/0?f=pjson","https://geo.sandag.org/server/rest/services/Hosted/Fire_Hazard_Severity_Zones/FeatureServer?f=pjson"]:
    r=get(u); print(u,r.status_code); print(r.text[:1500])

import sys,json; sys.path.insert(0,"recon/scripts")
from _http import get
env=json.dumps({"xmin":-117.36,"ymin":32.72,"xmax":-117.19,"ymax":32.90,"spatialReference":{"wkid":4326}})
def info(u):
    j=get(u+"?f=pjson").json(); print("svc extent",j.get("fullExtent"), (j.get("description") or "")[:300])
    return j
# BigBear count/extent
u="https://services2.arcgis.com/safmkHh6IfIYbpgO/arcgis/rest/services/FHSZ_LRA2025/FeatureServer/22"
L=get(u+"?f=pjson").json(); print("BigBear ext",L.get("extent")); print(get(u+"/query",params={"where":"1=1","returnCountOnly":"true","f":"json"}).json())
# SDSU San Diego mirror
u="https://services1.arcgis.com/SIYkiqjmENweC50g/arcgis/rest/services/FIRE_HAZARD_SEVERITY_ZONES_SD_/FeatureServer"
j=info(u)
for l in j.get("layers",[]):
    L=get(f"{u}/{l['id']}?f=pjson").json(); print(l["name"],[f["name"] for f in L.get("fields",[])],L.get("extent"))
    print(get(f"{u}/{l['id']}/query",params={"where":"1=1","returnCountOnly":"true","f":"json"}).json())
    q=get(f"{u}/{l['id']}/query",params={"where":"1=1","geometry":env,"geometryType":"esriGeometryEnvelope","inSR":4326,"spatialRel":"esriSpatialRelIntersects","outFields":"*","returnGeometry":"false","f":"json"}).json()
    print("bbox feats",len(q.get("features",[])),q.get("error"))
    from collections import Counter
    print(Counter(json.dumps({k:v for k,v in f["attributes"].items() if "Shape" not in k and k!="OBJECTID"},sort_keys=True) for f in q.get("features",[])).most_common(8))

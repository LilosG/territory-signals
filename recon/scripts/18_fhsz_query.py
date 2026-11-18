import sys,json; sys.path.insert(0,"recon/scripts")
from _http import get
env=json.dumps({"xmin":-117.36,"ymin":32.72,"xmax":-117.19,"ymax":32.90,"spatialReference":{"wkid":4326}})
for name,u in [("MTC FHSZ_2025 (Updated 2026)","https://services3.arcgis.com/i2dkYWmb4wHvYPda/arcgis/rest/services/FHSZ_2025/FeatureServer"),("FHSZ_LRA2025 (BigBear mirror)","https://services2.arcgis.com/safmkHh6IfIYbpgO/arcgis/rest/services/FHSZ_LRA2025/FeatureServer")]:
    print("=====",name)
    j=get(u+"?f=pjson").json()
    print("layers",[(l["id"],l["name"]) for l in j.get("layers",[])]); print((j.get("description") or j.get("serviceDescription") or "")[:500]); 
    for l in j.get("layers",[]):
        L=get(f"{u}/{l['id']}?f=pjson").json()
        print(l["name"],"fields",[f["name"] for f in L.get("fields",[])], "maxRec",L.get("maxRecordCount"))
        q=get(f"{u}/{l['id']}/query",params={"where":"1=1","geometry":env,"geometryType":"esriGeometryEnvelope","inSR":4326,"spatialRel":"esriSpatialRelIntersects","outFields":"*","returnGeometry":"false","f":"json"}).json()
        feats=q.get("features",[]); print("features in bbox:",len(feats), q.get("error"))
        for f in feats[:10]: print("  ",f["attributes"])

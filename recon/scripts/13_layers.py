import geopandas as gpd, pandas as pd, json
R="recon/raw/"; S="recon/samples/"
cp=gpd.read_file(R+"Community_Plan_SD.geojson"); print("CPA",cp.shape,cp.crs); print(list(cp.columns))
print(cp.drop(columns="geometry").head(3).to_string())
nm=[c for c in cp.columns if "NAME" in c.upper() or "CPNAME" in c.upper()]
print(nm)
for c in nm:
    print(c, sorted(cp[c].astype(str).unique())[:80])
mask=cp.apply(lambda r: any(k in " ".join(map(str,r.drop("geometry").values)).upper() for k in ["LA JOLLA","PACIFIC BEACH","MISSION BEACH"]),axis=1)
sel=cp[mask]; print(sel.drop(columns="geometry").to_string())
sel.to_crs(4326).to_file(S+"official_community_planning_areas_LJ_PB_MB.geojson",driver="GeoJSON")
z=gpd.read_file(R+"Zoning_Base_SD.geojson"); print("ZONING",z.shape,z.crs); print(list(z.columns)); print(z.drop(columns="geometry").head(3).to_string())
t=gpd.read_file(R+"Transit_Stops_GTFS.geojson"); print("TRANSIT",t.shape,t.crs); print(list(t.columns)); print(t.drop(columns="geometry").head(3).to_string())

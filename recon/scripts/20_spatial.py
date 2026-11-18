import sys,json; sys.path.insert(0,"recon/scripts")
from _http import get
import pandas as pd, geopandas as gpd
R="recon/raw/"; S="recon/samples/"
pp=pd.read_csv(R+"parcels_zip_subset.csv",dtype=str)
pp=pp.dropna(subset=["X_COORD","Y_COORD"]); pp=pp[pp.X_COORD.str.strip()!=""]
g=gpd.GeoDataFrame(pp,geometry=gpd.points_from_xy(pp.X_COORD.astype(float),pp.Y_COORD.astype(float)),crs=2230).to_crs(4326)
print("parcel points",len(g),g.total_bounds)
# CPA
cpa=gpd.read_file(R+"Community_Plan_SD.geojson")[["CPNAME","geometry"]]
j=gpd.sjoin(g,cpa,how="left",predicate="within")
print("\nZIP x CPA (parcel points):"); print(j.groupby(["zip5","CPNAME"],dropna=False).size().sort_values(ascending=False).head(12))
# zoning
z=gpd.read_file(R+"Zoning_Base_SD.geojson")[["ZONE_NAME","geometry"]]
jz=gpd.sjoin(g,z,how="left",predicate="within")
jz["zfam"]=jz.ZONE_NAME.str.extract(r"^([A-Z]+)")[0]
print("\nZoning family by zip:"); print(jz.groupby(["zip5","zfam"],dropna=False).size().unstack(0).sort_values("92037",ascending=False).head(15))
print("\nTop zone names:"); print(jz.groupby(["zip5","ZONE_NAME"]).size().sort_values(ascending=False).groupby(level=0).head(8))
print("RS single-family zoned parcels:",jz[jz.zfam=="RS"].groupby("zip5").size().to_dict(), "| RS & landuse 11:",jz[(jz.zfam=="RS")&(jz.ASR_LANDUSE.str.strip()=="11")].groupby("zip5").size().to_dict())
# transit
t=gpd.read_file(R+"Transit_Stops_GTFS.geojson")
tm=t.to_crs(2230); gm=g.to_crs(2230)
area=gm.groupby("zip5").geometry.apply(lambda s: s.union_all().convex_hull)
for zp,h in area.items():
    buf=h.buffer(2640)  # half mile ft
    inside=tm[tm.intersects(buf)]
    print(f"\nstops within 1/2 mi of {zp} parcel hull:",len(inside), inside.stop_agency.value_counts().to_dict(),"location_type",inside.location_type.value_counts().to_dict())
print("stop_agency overall",t.stop_agency.value_counts().to_dict())
# FHSZ (SDSU mirror of City VHFHSZ, older vintage)
u="https://services1.arcgis.com/SIYkiqjmENweC50g/arcgis/rest/services/FIRE_HAZARD_SEVERITY_ZONES_SD_/FeatureServer/0/query"
r=get(u,params={"where":"1=1","outFields":"FEATURE_NM","outSR":4326,"f":"geojson","resultRecordCount":2000}); open(R+"fhsz_sd_mirror.geojson","w").write(r.text)
f=gpd.read_file(R+"fhsz_sd_mirror.geojson"); print("\nFHSZ mirror",len(f),f.FEATURE_NM.value_counts().to_dict())
jf=gpd.sjoin(g,f,how="inner",predicate="within")
print("parcels inside mirror VHFHSZ polys:",jf.groupby(["zip5","FEATURE_NM"]).size().to_dict())
sel=jf[["APN","zip5","FEATURE_NM"]].head(200); sel.to_csv(S+"fhsz_vhfhsz_parcel_hits_sample.csv",index=False)
# SB9 / zoning sample
jz[["APN","zip5","ZONE_NAME","ASR_LANDUSE"]].sample(200,random_state=2).to_csv(S+"parcel_zoning_join_sample.csv",index=False)
t[t.within(gpd.GeoSeries(area.values,crs=2230).to_crs(4326).union_all().buffer(0.01))].drop(columns="geometry").head(200).to_csv(S+"transit_stops_near_study_area_sample.csv",index=False)

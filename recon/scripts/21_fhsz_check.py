import pandas as pd, geopandas as gpd
R="recon/raw/"
pp=pd.read_csv(R+"parcels_zip_subset.csv",dtype=str).dropna(subset=["X_COORD","Y_COORD"])
g=gpd.GeoDataFrame(pp,geometry=gpd.points_from_xy(pp.X_COORD.astype(float),pp.Y_COORD.astype(float)),crs=2230).to_crs(4326)
g=g[(g.geometry.x.between(-117.35,-117.19))&(g.geometry.y.between(32.72,32.90))]
print("in-bbox parcel points",g.zip5.value_counts().to_dict())
f=gpd.read_file(R+"fhsz_sd_mirror.geojson").reset_index(names="idx")
print(f.is_valid.value_counts().to_dict())
f["area_sqmi"]=f.to_crs(2230).area/27878400
j=gpd.sjoin(g,f[["idx","area_sqmi","geometry"]],how="inner",predicate="within")
print(j.groupby(["zip5","idx"]).size().rename("n").reset_index().merge(f[["idx","area_sqmi"]],on="idx").sort_values("n",ascending=False).head(10))
print(f.sort_values("area_sqmi",ascending=False)[["idx","area_sqmi"]].head(5)); print(f.total_bounds)
big=f.sort_values("area_sqmi",ascending=False).iloc[0]; print("largest poly bounds",big.geometry.bounds)
# Where do hit parcels sit? community
cpa=gpd.read_file(R+"Community_Plan_SD.geojson")[["CPNAME","geometry"]]
jj=gpd.sjoin(j.drop(columns="index_right"),cpa,how="left",predicate="within")
print(jj.groupby(["zip5","CPNAME"]).size())

import pandas as pd, numpy as np
R="recon/raw/"; S="recon/samples/"
p=pd.read_csv(R+"Parcels.csv",dtype=str,encoding="utf-8-sig",low_memory=False)
print(p.shape); print(list(p.columns))
p["zip5"]=p.SITUS_ZIP.str.strip().str[:5]
print("owner-like cols:",[c for c in p.columns if "OWN" in c.upper() or "NAME" in c.upper()])
t=p[p.zip5.isin(["92037","92109"])]
print("parcels by zip:\n",t.zip5.value_counts())
print("by juris/community:\n",t.groupby(["zip5","SITUS_JURIS"]).size())
print(t.groupby(["zip5","SITUS_COMMUNITY"]).size().sort_values(ascending=False).head(15))
print("land use top:\n",t.ASR_LANDUSE.value_counts().head(10))
print("OWNEROCC:\n",t.OWNEROCC.value_counts(dropna=False))
print("null/blank rates in zips:")
for c in ["APN","SITUS_ADDRESS","SITUS_STREET","ACREAGE","USABLE_SQ_FEET","ASR_ZONE","NUCLEUS_ZONE_CD","ASR_LANDUSE","YEAR_EFFECTIVE","TOTAL_LVG_AREA","DOCDATE","DOCTYPE","ASR_TOTAL","BEDROOMS"]:
    s=t[c].fillna("").str.strip(); print(f"  {c}: blank {(s=='').mean():.1%}  sample={s[s!=''].head(3).tolist()}")
d=pd.to_datetime(t.DOCDATE,format="%m%d%y",errors="coerce"); print("DOCDATE parsed range",d.min(),d.max(),"unparsed",d.isna().mean())
print(t.DOCTYPE.value_counts().head(10))
print("YEAR_EFFECTIVE dist:",t.YEAR_EFFECTIVE.str.strip().astype(float,errors="ignore").describe() if False else t.YEAR_EFFECTIVE.str.strip().head(5).tolist())
print("APN uniq:",t.APN.nunique(),"of",len(t))
cols=["APN","SITUS_ADDRESS","SITUS_PRE_DIR","SITUS_STREET","SITUS_SUFFIX","SITUS_SUITE","SITUS_ZIP","SITUS_COMMUNITY","ACREAGE","USABLE_SQ_FEET","ASR_ZONE","ASR_LANDUSE","NUCLEUS_ZONE_CD","NUCLEUS_USE_CD","UNITQTY","YEAR_EFFECTIVE","TOTAL_LVG_AREA","BEDROOMS","BATHS","DOCTYPE","DOCDATE","OWNEROCC","TAXSTAT","ASR_LAND","ASR_IMPR","ASR_TOTAL","X_COORD","Y_COORD"]
t[cols].sample(200,random_state=1).to_csv(S+"parcels_92037_92109_sample.csv",index=False)
t[["APN","zip5","SITUS_COMMUNITY","X_COORD","Y_COORD","ASR_ZONE","ASR_LANDUSE","USABLE_SQ_FEET","UNITQTY"]].to_parquet(R+"parcels_zip_subset.parquet") if False else t[["APN","zip5","SITUS_COMMUNITY","X_COORD","Y_COORD","ASR_ZONE","ASR_LANDUSE","UNITQTY","OWNEROCC","DOCDATE"]].to_csv(R+"parcels_zip_subset.csv",index=False)
# APN-join counts: permits & TTC
d2=pd.concat([pd.read_csv(R+n,dtype=str) for n in ["approvals_issued_2025_datasd.csv","approvals_issued_2026_datasd.csv"]])
d2["iss"]=pd.to_datetime(d2.APPROVAL_ISSUE_DATE,errors="coerce")
m=d2.merge(p[["APN","zip5"]].drop_duplicates("APN"),left_on="GIS_APN",right_on="APN",how="left")
print("permit rows matched to parcel:",m.zip5.notna().mean(), " null APN:",d2.GIS_APN.isna().mean())
m=m[(m.iss>="2025-11-18")&m.zip5.isin(["92037","92109"])]
print("last-12-mo issued approvals via APN join:",m.zip5.value_counts().to_dict())
print(m.groupby(["zip5","PROJECT_TYPE"]).size())
m.drop(columns=["APN"]).head(200).to_csv(S+"dev_permits_issued_92037_92109_sample.csv",index=False)

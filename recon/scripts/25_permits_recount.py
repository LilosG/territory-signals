import pandas as pd
R="recon/raw/"
d=pd.concat([pd.read_csv(R+n,dtype=str) for n in ["approvals_issued_2025_datasd.csv","approvals_issued_2026_datasd.csv"]])
d["iss"]=pd.to_datetime(d.APPROVAL_ISSUE_DATE,errors="coerce")
full=pd.read_csv(R+"Parcels.csv",dtype=str,encoding="utf-8-sig",usecols=["APN","SITUS_ZIP"]); full["zip5"]=full.SITUS_ZIP.str.strip().str[:5]
m=d.merge(full.drop_duplicates("APN"),left_on="GIS_APN",right_on="APN",how="left")
w=m[(m.iss>="2025-11-18")&m.zip5.isin(["92037","92109"])].copy()
w["PROJECT_TYPE"]=w.PROJECT_TYPE.fillna("(blank)")
print("rows",w.zip5.value_counts().to_dict(),"distinct projects",w.groupby("zip5").PROJECT_ID.nunique().to_dict())
print(w.groupby(["zip5","PROJECT_TYPE"]).size().unstack(0).fillna(0).astype(int).sort_values("92037",ascending=False))
print("blank PROJECT_TYPE share overall (2025-26 issued):",d.PROJECT_TYPE.isna().mean())
print("blank-type rows: project id format sample",w[w.PROJECT_TYPE=="(blank)"].PROJECT_ID.head(3).tolist(), "vs typed",w[w.PROJECT_TYPE!="(blank)"].PROJECT_ID.head(3).tolist())
print("blank-type approval types:",w[w.PROJECT_TYPE=="(blank)"].APPROVAL_TYPE.value_counts().head(6).to_dict())
res=w[w.APPROVAL_TYPE.str.contains("Building Permit|Demolition|Combination|ADU|Accessory",case=False,na=False)]
print("building/demo-ish approvals:",res.zip5.value_counts().to_dict())
print("ADU total>0:",pd.to_numeric(w.APPROVAL_ADU_TOTAL,errors="coerce").gt(0).groupby(w.zip5).sum().to_dict(), "DU net change>0:",pd.to_numeric(w.APPROVAL_DU_NET_CHANGE,errors="coerce").gt(0).groupby(w.zip5).sum().to_dict())
w.drop(columns=["APN"]).head(200).to_csv("recon/samples/dev_permits_issued_92037_92109_sample.csv",index=False)
print("permit holder sample:",w.APPROVAL_PERMIT_HOLDER.dropna().head(3).tolist())

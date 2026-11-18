import sys,re,os; sys.path.insert(0, "recon/scripts")
from _http import get
import pandas as pd
R="recon/raw/"; S="recon/samples/"
def dl(url,name):
    p=R+name
    if not os.path.exists(p):
        r=get(url,stream=True,timeout=600); r.raise_for_status()
        with open(p,"wb") as f:
            for c in r.iter_content(1<<20): f.write(c)
    return p
B="https://seshat.datasd.org/development_permits/"
for n in ["approvals_issued_2025_datasd.csv","approvals_issued_2026_datasd.csv"]: dl(B+n,n)
dl("https://seshat.datasd.org/development_permits_set2/permits_set2_datasd_dict.csv","permits_set2_dict.csv")
d=pd.concat([pd.read_csv(R+n,dtype=str) for n in ["approvals_issued_2025_datasd.csv","approvals_issued_2026_datasd.csv"]])
print(d.shape); print(list(d.columns))
d["zip"]=d.GIS_ADDRESS.str.extract(r"(\d{5})\s*$")[0]
print("zip null",d.zip.isna().sum(),"APN null",d.GIS_APN.isna().sum())
d["iss"]=pd.to_datetime(d.APPROVAL_ISSUE_DATE,errors="coerce")
print("issue range",d.iss.min(),d.iss.max())
l12=d[(d.iss>="2025-11-17")&d.zip.isin(["92037","92109"])]
print("last-12mo issued rows",len(l12))
print(l12.groupby(["zip","PROJECT_TYPE"]).size())
print(l12.groupby(["zip","APPROVAL_TYPE"]).size().sort_values(ascending=False).head(25))
print(d.PROJECT_STATUS.value_counts().head(), d.APPROVAL_STATUS.value_counts().head())
print(d.PROJECT_TYPE.value_counts())
l12.head(200).to_csv(S+"dev_permits_issued_92037_92109_sample.csv",index=False)
print(open(R+"permits_set2_dict.csv").read()[:2500])

import re, pandas as pd
R="recon/raw/"
apns=[]
for ln in open(R+"Notice-of-Impending-Power-to-Sell-Tax-Defaulted-Property-June-5-12-19-2026.pdf.txt"):
    m=re.match(r"^\s*(\d{3}-\d{3}-\d{2}-\d{2})\b",ln)
    if m: apns.append(m[1].replace("-",""))
print("APN lines",len(apns),"unique",len(set(apns)))
full=pd.read_csv(R+"Parcels.csv",dtype=str,encoding="utf-8-sig",usecols=["APN","SITUS_ZIP"]); full["zip5"]=full.SITUS_ZIP.str.strip().str[:5]
m=pd.DataFrame({"APN":apns}).merge(full.drop_duplicates("APN"),on="APN",how="left")
print("matched",m.zip5.notna().mean(),"| 92037/92109:",m.zip5.value_counts().reindex(["92037","92109"]).to_dict())
# also 7102 auction notice
a=[x.replace("-","") for x in re.findall(r"\b(\d{3}-\d{3}-\d{2}-\d{2})\b",open(R+"Notice-of-Public-Online-Auction-7102.pdf.txt").read())]
print("auction 7102 APNs",len(a)); a=pd.DataFrame({"APN":a}).merge(full.drop_duplicates("APN"),on="APN",how="left"); print(a.zip5.isin(["92037","92109"]).sum(), a.zip5.notna().mean())

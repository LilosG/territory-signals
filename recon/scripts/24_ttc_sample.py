import re, pandas as pd
R="recon/raw/"
rows=[]
for ln in open(R+"Notice-of-Impending-Power-to-Sell-Tax-Defaulted-Property-June-5-12-19-2026.pdf.txt"):
    m=re.match(r"^\s*(\d{3}-\d{3}-\d{2}-\d{2})\s+(.*)$",ln)
    if m: rows.append((m[1].replace("-",""),m[1],m[2].strip()))
d=pd.DataFrame(rows,columns=["APN","apn_fmt","rest_of_line_raw"])
full=pd.read_csv(R+"Parcels.csv",dtype=str,encoding="utf-8-sig",usecols=["APN","SITUS_ZIP"]); full["zip5"]=full.SITUS_ZIP.str.strip().str[:5]
m=d.merge(full.drop_duplicates("APN"),on="APN",how="left"); m=m[m.zip5.isin(["92037","92109"])].drop(columns=["APN","SITUS_ZIP"])
m.to_csv("recon/samples/sdttc_impending_power_to_sell_92037_92109.csv",index=False); print(len(m))

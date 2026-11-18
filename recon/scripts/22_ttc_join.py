import re, pandas as pd
R="recon/raw/"; S="recon/samples/"
rows=[]
for ln in open(R+"Notice-of-Impending-Power-to-Sell-Tax-Defaulted-Property-June-5-12-19-2026.pdf.txt"):
    m=re.match(r"^(\d{3}-\d{3}-\d{2}-\d{2})\s+(.*?)\s+(\d{5})\s+(.*?)\s+\$([\d,\.]+)\s*$",ln.strip())
    if m: rows.append(dict(apn=m[1].replace("-",""),apn_fmt=m[1],assessee=m[2],street_no=m[3],street=m[4],amount_to_redeem=m[5]))
d=pd.DataFrame(rows); print("parsed rows",len(d),"(raw APN-start lines: see earlier ~1034)")
p=pd.read_csv(R+"parcels_zip_subset.csv",dtype=str)[["APN","zip5","SITUS_COMMUNITY"]]
full=pd.read_csv(R+"Parcels.csv",dtype=str,encoding="utf-8-sig",usecols=["APN","SITUS_ZIP","SITUS_COMMUNITY","SITUS_JURIS"])
full["zip5"]=full.SITUS_ZIP.str.strip().str[:5]
m=d.merge(full.drop_duplicates("APN"),left_on="apn",right_on="APN",how="left")
print("matched to parcels:",m.APN.notna().mean())
print("in 92037/92109 by parcel zip:",m.zip5.isin(["92037","92109"]).sum(), m[m.zip5.isin(["92037","92109"])].zip5.value_counts().to_dict())
print(m.SITUS_JURIS.value_counts().head(5).to_dict())
print(m[m.zip5.isin(["92037","92109"])][["apn_fmt","assessee","street_no","street","amount_to_redeem","zip5"]].to_string())
m[m.zip5.isin(["92037","92109"])][["apn_fmt","street_no","street","amount_to_redeem","zip5"]].head(200).to_csv(S+"sdttc_impending_power_to_sell_92037_92109.csv",index=False)

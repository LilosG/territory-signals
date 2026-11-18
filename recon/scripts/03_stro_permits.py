import sys,re,os; sys.path.insert(0, "recon/scripts")
from _http import get
import pandas as pd
R="recon/raw/"; S="recon/samples/"
def dl(url,name):
    p=R+name
    if not os.path.exists(p):
        r=get(url,stream=True,timeout=300); r.raise_for_status()
        with open(p,"wb") as f:
            for c in r.iter_content(1<<20): f.write(c)
    return p
# terms
t=get("https://data.sandiego.gov/help/guides/terms/").text
print(re.sub(r"\s+"," ",re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>"," ",t,flags=re.S))[:3000])
# STRO
for u,n in [("stro_licenses_datasd.csv",)*2,("stro_licenses_dictionary_datasd.csv",)*2,("stro_licenses_tier_definitions_datasd.csv",)*2]:
    dl("https://seshat.datasd.org/stro_licenses/"+u,n)
print(open(R+"stro_licenses_tier_definitions_datasd.csv").read())
d=pd.read_csv(R+"stro_licenses_datasd.csv",dtype=str)
print(d.shape); print(list(d.columns))
print(d.zip.value_counts().head(8))
sub=d[d.zip.isin(["92037","92109"])]
print(sub.groupby(["zip","tier"]).size())
print(sub.groupby(["community_planning_area"]).size())
print("expiry range",d.date_expiration.min(),d.date_expiration.max())
print("nulls",d.isna().sum()[lambda s:s>0].to_dict())
print("distinct host names in zips:",sub.host_contact_name.nunique(), "multi-license hosts:",(sub.host_contact_name.value_counts()>1).sum())
sub.head(200).drop(columns=["local_contact_phone"],errors="ignore").to_csv(S+"stro_licenses_92037_92109_sample.csv",index=False)

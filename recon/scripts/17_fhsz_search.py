import sys,json; sys.path.insert(0,"recon/scripts")
from _http import get
r=get("https://www.arcgis.com/sharing/rest/search",params={"f":"json","num":15,"q":'title:"Fire Hazard Severity Zones" AND (LRA OR "Local Responsibility") AND type:"Feature Service" AND access:public'})
for x in r.json().get("results",[]): print(x["title"],"|",x["owner"],"|",x["url"],"|",x.get("modified"),"|",x["id"])

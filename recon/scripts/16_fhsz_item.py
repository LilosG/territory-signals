import sys,json; sys.path.insert(0,"recon/scripts")
from _http import get
r=get("https://www.arcgis.com/sharing/rest/content/items/31219c833eb54598ba83d09fa0adb346?f=json"); print(r.status_code)
j=r.json(); print({k:j.get(k) for k in ["title","url","modified","type","licenseInfo","accessInformation","snippet"]})
print((j.get("description") or "")[:1200])
u=j.get("url")
if u:
    L=get(u.rstrip("/")+"/0?f=pjson").json() if not u.rstrip("/").split("/")[-1].isdigit() else get(u+"?f=pjson").json()
    print(L.get("name"),[f["name"] for f in L.get("fields",[])], L.get("maxRecordCount"))

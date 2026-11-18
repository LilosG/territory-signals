import sys; sys.path.insert(0,"recon/scripts")
import requests,time
from _http import UA
B="https://geo.sandag.org/server/rest/directories/downloads/"
for n in ["Address_Points.csv","Address_Points.geojson","Community_Plan_SD.geojson","Zoning_Base_SD.geojson","Transit_Stops_GTFS.geojson","Transit_Stops_GTFS.csv","Parcels.csv","Parcels_shapefile.zip","Parcels.geojson","Council_Districts.geojson"]:
    r=requests.head(B+n,headers={"User-Agent":UA},timeout=60,allow_redirects=True)
    print(n,r.status_code,r.headers.get("content-length"),r.headers.get("last-modified")); time.sleep(2.1)

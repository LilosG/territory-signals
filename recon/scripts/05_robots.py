import sys; sys.path.insert(0,"recon/scripts")
from _http import get
for h in ["webmaps.sandiego.gov","geo.sandag.org","www.sdcourt.ca.gov","sdcourt.ca.gov","www.capublicnotice.com","www.sdttc.com","www.sandiegocounty.gov","gis.data.cnra.ca.gov","osfm.fire.ca.gov","www.sandiego.gov","www.legacy.com","www.sandiegouniontribune.com","www.lajollalight.com"]:
    try:
        r=get(f"https://{h}/robots.txt",timeout=30); print("=====",h,r.status_code); print(r.text[:700] if r.status_code==200 else "")
    except Exception as e: print("=====",h,"ERR",e)

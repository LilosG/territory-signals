import sys,os,re; sys.path.insert(0,"recon/scripts")
from _http import get
from pypdf import PdfReader
B="https://www.sdttc.com/content/dam/ttc/docs/taxcollection/"
for n in ["Notice-of-Impending-Power-to-Sell-Tax-Defaulted-Property-June-5-12-19-2026.pdf","Notice-of-Public-Online-Auction-7102.pdf"]:
    p="recon/raw/"+n
    if not os.path.exists(p):
        r=get(B+n,timeout=300); print(n,r.status_code,r.headers.get("content-type"),len(r.content)); open(p,"wb").write(r.content)
    rd=PdfReader(p); print("=====",n,"pages",len(rd.pages))
    txt="\n".join(pg.extract_text() or "" for pg in rd.pages)
    open(p+".txt","w").write(txt)
    print(txt[:1800]); print("...")
    print("chars",len(txt))

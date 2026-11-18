import time, requests, urllib.parse
UA = "territory-signals-recon (mike@lilosgrowth.com)"
_last = {}
DELAY = {"gis-sangis1.hub.arcgis.com":60,"www.sangis.org":60}  # robots.txt Crawl-delay: 60
def get(url, **kw):
    host = urllib.parse.urlparse(url).netloc
    wait = DELAY.get(host,2.0) - (time.time() - _last.get(host, 0))
    if wait > 0: time.sleep(wait)
    h = kw.pop("headers", {}); h["User-Agent"] = UA
    r = requests.get(url, headers=h, timeout=kw.pop("timeout", 60), **kw)
    _last[host] = time.time()
    return r

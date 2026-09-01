import re
import time
import urllib.parse
from collections import OrderedDict
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

MAX_TOTAL_RESULTS = 500
MAX_PAGES_PER_SOURCE = 10
MAX_RECORDS_PER_SOURCE = 250
REQUEST_TIMEOUT = 10
BROWSER_TIMEOUT = 12000
SEARCH_BUDGET_SECONDS = 70
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36"

REGION_AREAS = {
    "Kampala": ["kampala", "central division", "kawempe", "nakawa", "makindye", "rubaga", "lubaga", "ntinda", "kololo", "bukoto", "muyenga", "kabalagala", "katwe", "makerere", "bugolobi", "kireka"],
    "Wakiso": ["wakiso", "kira", "nansana", "entebbe", "kajansi", "namugongo", "kyaliwajjala", "bweyogerere", "buloba", "kasangati", "gayaza", "mpererwe", "kireka", "kajjansi"],
    "Mukono": ["mukono", "seeta", "sonde", "namanve", "lugazi", "nakisunga", "nkokonjeru"],
    "Masaka": ["masaka", "nyendo", "bukakata", "kijjabwemi"],
    "Jinja": ["jinja", "bugembe", "mpumudde", "kimaka", "walukuba", "budhumbuli", "masese"],
    "Western Uganda": ["western uganda", "mbarara", "fort portal", "fort-port", "kabale", "kasese", "bushenyi", "ibanda", "ntungamo", "rukungiri", "kanungu", "hoima", "bundibugyo", "kisoro", "sheema", "rubirizi", "mitooma", "kibaale"],
}

REGION_BBOX = {
    "Kampala": "0.25,32.45,0.42,32.70",
    "Wakiso": "0.05,32.30,0.60,32.75",
    "Mukono": "0.20,32.60,0.55,32.90",
    "Masaka": "-0.45,31.60,-0.20,31.85",
    "Jinja": "0.35,33.15,0.55,33.35",
    "Western Uganda": "-0.80,29.40,1.50,31.50",
}

OVERPASS = ["https://overpass.private.coffee/api/interpreter", "https://overpass-api.de/api/interpreter"]


def clean_text(v):
    if v is None: return "N/A"
    v = re.sub(r"\s+", " ", str(v)).strip()
    return v or "N/A"


def norm(v):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", clean_text(v).lower())).strip()


def slug(v):
    return re.sub(r"-+", "-", norm(v).replace(" ", "-"))


def phone_from(text):
    if not text: return "N/A"
    for p in (r"\+256[\s()./-]*[0-9][\s()./-]*[0-9]{2,}[\s()./-]*[0-9]{3,}", r"0[357][0-9][\s()./-]*[0-9]{3,}[\s()./-]*[0-9]{3,}", r"0[24][0-9]{2}[\s-]*[0-9]{5,}"):
        m = re.search(p, text)
        if m: return clean_text(m.group(0))
    return "N/A"


def make_record(name, region, keyword, source, url, phone="N/A", website="N/A", address="N/A", rating="N/A", lat="N/A", lng="N/A", category=None):
    return {"Company Name": clean_text(name), "Region": region, "Search Query": keyword, "Category": clean_text(category or keyword), "Business Deals In": clean_text(category or keyword), "Phone Contact": clean_text(phone), "Website": clean_text(website), "Physical Address": clean_text(address), "Rating": clean_text(rating), "Lat": clean_text(lat), "Lng": clean_text(lng), "Data Source": source, "Source URL": url}


def region_match(address, region):
    a = norm(address)
    if not a or a == "n a": return True
    return any(norm(x) in a for x in REGION_AREAS.get(region, [region]))


def http_html(url):
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}, timeout=REQUEST_TIMEOUT)
        return r.text if r.status_code == 200 and len(r.text) > 500 else None
    except requests.RequestException:
        return None


def browser_html(page, url):
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)
        page.wait_for_timeout(500)
        return page.content()
    except Exception:
        return None


def get_html(page, url):
    html = http_html(url)
    if html: return html
    return browser_html(page, url) if page else None


def profile_links(soup, patterns, base):
    out=[]
    for a in soup.find_all("a", href=True):
        href=a["href"]
        if any(p in href.lower() for p in patterns):
            u=urllib.parse.urljoin(base, href)
            if u not in out: out.append(u)
    return out


def parse_generic_cards(soup, region, keyword, source, page_url, base, patterns):
    records=[]
    links=profile_links(soup, patterns, base)
    for u in links[:MAX_RECORDS_PER_SOURCE]:
        a=soup.find("a", href=lambda x: x and urllib.parse.urljoin(base,x)==u)
        if not a: continue
        name=clean_text(a.get_text(" ", strip=True))
        if len(name)<2 or norm(name) in {"view profile","read more","details"}: continue
        parent=a
        for _ in range(5):
            if parent.parent: parent=parent.parent
        context=clean_text(parent.get_text(" ", strip=True))
        phone=phone_from(context)
        website="N/A"
        for x in parent.find_all("a", href=True):
            h=x["href"]
            if h.startswith("http") and base not in h:
                website=h; break
        records.append(make_record(name, region, keyword, source, u, phone, website, context[:500]))
    return records


def yellow_urls(region, keyword):
    base="https://www.yellow.ug"
    s=slug(keyword)
    r=slug(region)
    # Exact category URL is attempted for every keyword; this makes the search sector-agnostic.
    return [f"{base}/category/{s}/city%3A{r}", f"{base}/category/{s}"]


def scrape_yellow(page, region, keyword, deadline):
    out=[]; seen=set()
    for start in yellow_urls(region, keyword):
        for n in range(1, MAX_PAGES_PER_SOURCE+1):
            if time.monotonic()>=deadline or len(out)>=MAX_RECORDS_PER_SOURCE: return out
            if n==1: url=start
            else:
                parts=urllib.parse.urlsplit(start)
                path=parts.path.rstrip("/")
                url=urllib.parse.urlunsplit((parts.scheme,parts.netloc,f"{path.rsplit('/',1)[0]}/{n}/{path.rsplit('/',1)[-1]}","","")) if "/city%3A" in path else f"{start.rstrip('/')}/{n}"
            if url in seen: continue
            seen.add(url)
            html=get_html(page,url)
            if not html: continue
            soup=BeautifulSoup(html,"html.parser")
            recs=parse_generic_cards(soup,region,keyword,"Yellow Uganda",url,"https://www.yellow.ug",["/company/","/business/"])
            out.extend(recs)
            if not recs: break
    return out[:MAX_RECORDS_PER_SOURCE]


def hotfrog_url(region, keyword):
    return f"https://www.hotfrog.ug/search/{slug(region)}/{urllib.parse.quote(slug(keyword))}"


def scrape_hotfrog(page, region, keyword, deadline):
    out=[]; url=hotfrog_url(region,keyword); seen=set()
    for _ in range(MAX_PAGES_PER_SOURCE):
        if time.monotonic()>=deadline or len(out)>=MAX_RECORDS_PER_SOURCE or url in seen: break
        seen.add(url); html=get_html(page,url)
        if not html: break
        soup=BeautifulSoup(html,"html.parser")
        recs=parse_generic_cards(soup,region,keyword,"Hotfrog Uganda",url,"https://www.hotfrog.ug",["/company/","/business/"])
        out.extend(recs)
        nxt=None
        for a in soup.find_all("a",href=True):
            if norm(a.get_text(" ",strip=True)) in {"next","next page"}:
                nxt=urllib.parse.urljoin(url,a["href"]); break
        if not nxt: break
        url=nxt
    return out[:MAX_RECORDS_PER_SOURCE]


def finder_urls(region, keyword):
    s=slug(keyword)
    return [f"https://finderafrica.com/listing-category/{s}/", f"https://finderafrica.com/?s={urllib.parse.quote(keyword)}"]


def scrape_finder(page, region, keyword, deadline):
    out=[]; seen=set()
    for start in finder_urls(region,keyword):
        url=start
        for _ in range(MAX_PAGES_PER_SOURCE):
            if time.monotonic()>=deadline or len(out)>=MAX_RECORDS_PER_SOURCE or url in seen: break
            seen.add(url); html=get_html(page,url)
            if not html: break
            soup=BeautifulSoup(html,"html.parser")
            recs=parse_generic_cards(soup,region,keyword,"FinderAfrica Uganda",url,"https://finderafrica.com",["/listing/","/business/"])
            out.extend(recs)
            nxt=None
            for a in soup.find_all("a",href=True):
                if norm(a.get_text(" ",strip=True)) in {"next","next page"}:
                    nxt=urllib.parse.urljoin(url,a["href"]); break
            if not nxt: break
            url=nxt
    return out[:MAX_RECORDS_PER_SOURCE]


def scrape_yellowpages(page, region, keyword, deadline):
    # Generic search attempts; the parser deliberately avoids assuming one CSS class.
    out=[]
    queries=[f"https://www.yellowpages-uganda.com/?s={urllib.parse.quote(keyword)}", f"https://www.yellowpages-uganda.com/search/?q={urllib.parse.quote(keyword)}"]
    for url in queries:
        if time.monotonic()>=deadline: break
        html=get_html(page,url)
        if not html: continue
        soup=BeautifulSoup(html,"html.parser")
        recs=[]
        for a in soup.find_all("a",href=True):
            text=clean_text(a.get_text(" ",strip=True))
            href=urllib.parse.urljoin(url,a["href"])
            if len(text)>2 and any(x in href.lower() for x in ["business","company","listing"]):
                parent=a
                for _ in range(4):
                    if parent.parent: parent=parent.parent
                context=clean_text(parent.get_text(" ",strip=True))
                if norm(keyword) not in norm(context) and norm(region) not in norm(context): continue
                recs.append(make_record(text,region,keyword,"Yellow Pages Uganda",href,phone_from(context),address=context[:500]))
        out.extend(recs)
        if out: break
    return out[:MAX_RECORDS_PER_SOURCE]


def scrape_kcca(page, region, keyword, deadline):
    if region!="Kampala" or time.monotonic()>=deadline: return []
    url="https://kcca.go.ug/businesses"
    html=get_html(page,url)
    if not html: return []
    soup=BeautifulSoup(html,"html.parser")
    out=[]
    for row in soup.select("table tr"):
        text=clean_text(row.get_text(" ",strip=True))
        if norm(keyword) not in norm(text): continue
        cells=[clean_text(x.get_text(" ",strip=True)) for x in row.find_all(["td","th"])]
        if cells: out.append(make_record(cells[-1],region,keyword,"KCCA Business Register",url,address=" | ".join(cells)))
        if len(out)>=MAX_RECORDS_PER_SOURCE: break
    return out


def osm_query(region, keyword):
    bbox=REGION_BBOX[region]
    q=re.escape(keyword)
    filters=[f'["name"~"{q}",i]',f'["brand"~"{q}",i]',f'["operator"~"{q}",i]',f'["description"~"{q}",i]']
    blocks=[]
    for f in filters:
        blocks += [f"node{f}({bbox});",f"way{f}({bbox});",f"relation{f}({bbox});"]
    return "[out:json][timeout:35];(\n"+"\n".join(blocks)+"\n);out center tags;"


def fetch_osm_grid_data(region_name, keyword):
    if region_name not in REGION_BBOX: return []
    query=osm_query(region_name,keyword)
    for endpoint in OVERPASS:
        try:
            r=requests.post(endpoint,data=query,headers={"User-Agent":"UgandaBusinessLeadGenerator/1.0"},timeout=40)
            if r.status_code!=200: continue
            out=[]
            for el in r.json().get("elements",[]):
                tags=el.get("tags",{}); name=clean_text(tags.get("name"))
                if name=="N/A": continue
                c=el.get("center",{}); lat=el.get("lat",c.get("lat","N/A")); lng=el.get("lon",c.get("lon","N/A"))
                addr=", ".join([str(tags.get(k)) for k in ["addr:housenumber","addr:street","addr:city","addr:district"] if tags.get(k)]) or region_name
                out.append(make_record(name,region_name,keyword,"OpenStreetMap",endpoint,tags.get("phone") or tags.get("contact:phone","N/A"),tags.get("website") or tags.get("contact:website","N/A"),addr,tags.get("rating","N/A"),lat,lng,tags.get("shop") or tags.get("amenity") or tags.get("office") or tags.get("craft") or keyword))
                if len(out)>=MAX_RECORDS_PER_SOURCE: break
            return out
        except Exception:
            continue
    return []


def identity(r):
    phone=re.sub(r"\D","",clean_text(r.get("Phone Contact")))
    name=norm(r.get("Company Name")); addr=norm(r.get("Physical Address"))
    if phone and phone not in {"na","n a"}: return ("phone",phone)
    if name: return ("name",name,addr[:120])
    return None


def merge(a,b):
    for k in ["Phone Contact","Website","Physical Address","Rating","Lat","Lng"]:
        if clean_text(a.get(k))=="N/A" and clean_text(b.get(k))!="N/A": a[k]=b[k]
    for k in ["Data Source","Source URL"]:
        vals=set(filter(None,[x.strip() for x in (clean_text(a.get(k))+" | "+clean_text(b.get(k))).split("|")]))
        a[k]=" | ".join(sorted(vals))
    return a


def scrape_ugandan_directories(region_name, keyword):
    deadline=time.monotonic()+SEARCH_BUDGET_SECONDS
    all_records=[]
    with sync_playwright() as p:
        browser=None; context=None; page=None
        try:
            browser=p.chromium.launch(headless=True)
            context=browser.new_context(user_agent=USER_AGENT)
            page=context.new_page()
        except Exception:
            pass
        jobs=[("Yellow Uganda",scrape_yellow),("Hotfrog Uganda",scrape_hotfrog),("FinderAfrica Uganda",scrape_finder),("Yellow Pages Uganda",scrape_yellowpages),("KCCA Business Register",scrape_kcca)]
        for _,job in jobs:
            if time.monotonic()>=deadline: break
            try: all_records.extend(job(page,region_name,keyword,deadline))
            except Exception: pass
        try:
            if context: context.close()
            if browser: browser.close()
        except Exception: pass
    # Soft region filter; unknown address is retained rather than discarded.
    filtered=[r for r in all_records if region_match(r.get("Physical Address"),region_name)]
    return deduplicate_records(filtered)[:MAX_TOTAL_RESULTS]


def deduplicate_records(records):
    unique=OrderedDict()
    for r in records:
        key=identity(r)
        if not key: continue
        unique[key]=merge(unique[key],r) if key in unique else r
    return list(unique.values())

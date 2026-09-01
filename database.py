import sqlite3
import pandas as pd

DB_NAME = "uganda_leads.db"

COLUMNS = [
    "company_name", "region", "search_query", "category", "business_deals_in",
    "phone_contact", "website", "physical_address", "rating", "lat", "lng",
    "data_source", "source_url"
]


def _connect():
    return sqlite3.connect(DB_NAME)


def init_database():
    conn=_connect(); cur=conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS business_leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company_name TEXT,
        region TEXT,
        search_query TEXT,
        category TEXT,
        business_deals_in TEXT,
        phone_contact TEXT,
        website TEXT,
        physical_address TEXT,
        rating TEXT,
        lat TEXT,
        lng TEXT,
        data_source TEXT,
        source_url TEXT,
        UNIQUE(company_name, physical_address)
    )""")
    cur.execute("PRAGMA table_info(business_leads)")
    existing={r[1] for r in cur.fetchall()}
    if "search_query" not in existing:
        cur.execute("ALTER TABLE business_leads ADD COLUMN search_query TEXT")
    conn.commit(); conn.close()


def _clean(v):
    return "N/A" if v is None or str(v).strip()=="" else str(v).strip()


def _merge_text(old,new):
    old=_clean(old); new=_clean(new)
    if old=="N/A": return new
    if new=="N/A" or new==old: return old
    vals=[]
    for x in (old+" | "+new).split("|"):
        x=x.strip()
        if x and x not in vals: vals.append(x)
    return " | ".join(vals)


def _find_existing(cur,name,address):
    cur.execute("SELECT id FROM business_leads WHERE lower(company_name)=lower(?) AND lower(physical_address)=lower(?) LIMIT 1",(name,address))
    row=cur.fetchone()
    return row[0] if row else None


def save_and_deduplicate(records):
    if not records: return 0
    init_database(); conn=_connect(); cur=conn.cursor(); saved=0
    for r in records:
        try:
            name=_clean(r.get("Company Name")); address=_clean(r.get("Physical Address"))
            rowid=_find_existing(cur,name,address)
            vals={
                "search_query":_clean(r.get("Search Query") or r.get("Category")),
                "category":_clean(r.get("Category")),
                "business_deals_in":_clean(r.get("Business Deals In")),
                "phone_contact":_clean(r.get("Phone Contact")),
                "website":_clean(r.get("Website")),
                "physical_address":address,
                "rating":_clean(r.get("Rating")),
                "lat":_clean(r.get("Lat")), "lng":_clean(r.get("Lng")),
                "data_source":_clean(r.get("Data Source")), "source_url":_clean(r.get("Source URL"))
            }
            if rowid:
                cur.execute("SELECT search_query,category,business_deals_in,phone_contact,website,physical_address,rating,lat,lng,data_source,source_url FROM business_leads WHERE id=?",(rowid,))
                old=dict(zip(["search_query","category","business_deals_in","phone_contact","website","physical_address","rating","lat","lng","data_source","source_url"],cur.fetchone()))
                merged={k:_merge_text(old.get(k),v) for k,v in vals.items()}
                cur.execute("""UPDATE business_leads SET search_query=?,category=?,business_deals_in=?,phone_contact=?,website=?,physical_address=?,rating=?,lat=?,lng=?,data_source=?,source_url=? WHERE id=?""",tuple(merged[k] for k in ["search_query","category","business_deals_in","phone_contact","website","physical_address","rating","lat","lng","data_source","source_url"])+(rowid,))
            else:
                cur.execute("""INSERT INTO business_leads (company_name,region,search_query,category,business_deals_in,phone_contact,website,physical_address,rating,lat,lng,data_source,source_url) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",(name,_clean(r.get("Region")),vals["search_query"],vals["category"],vals["business_deals_in"],vals["phone_contact"],vals["website"],vals["physical_address"],vals["rating"],vals["lat"],vals["lng"],vals["data_source"],vals["source_url"]))
            saved+=1
        except Exception:
            continue
    conn.commit(); conn.close(); return saved


def get_leads(region=None, search_query=None):
    init_database(); conn=_connect(); clauses=[]; params=[]
    if region:
        clauses.append("lower(region)=lower(?)"); params.append(region)
    if search_query:
        # Match the actual search query, not the source's category label.
        clauses.append("lower(search_query)=lower(?)"); params.append(search_query)
    where=(" WHERE "+" AND ".join(clauses)) if clauses else ""
    df=pd.read_sql_query("SELECT * FROM business_leads"+where+" ORDER BY id DESC",conn,params=params)
    conn.close(); return df


def get_all_leads():
    return get_leads()

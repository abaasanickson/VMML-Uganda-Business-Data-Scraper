Uganda Business Lead Generator — maximum public coverage
This build is designed for a debt-recovery lead-generation workflow.

What changed
No paid Google Maps/Places API.
Searches every configured source independently instead of stopping after the first useful source.
No artificial 7/10-result ceiling: each source follows public pagination/category pages until exhausted, the source time slice expires, or the source itself stops returning results.
Yellow Uganda is searched through its real category/location structure and individual company profiles are opened when phone/address/description is missing. Yellow Uganda currently advertises 37,830 verified company listings and says standard listings can contain phone/WhatsApp/fax, address, description and website.
Find.ug is included as another broad Uganda directory and its business profiles can expose phone numbers, addresses, categories and descriptions.
National SME Portal is included for district/sector coverage. Its public directory exposes business name, sector and district and filters for region/sub-region/district.
Western Uganda is expanded across multiple towns/districts instead of one small map box.
OpenStreetMap uses name, brand, operator, description and multiple business-tag fields instead of requiring an exact OSM tag equal to the search word.
Phone extraction captures multiple Ugandan numbers and merges them across sources.
Missing phone/address fields are enriched from public business profile pages where available.
Physical Address is never filled with only Wakiso, Western Uganda, etc. If a source has only a district, it is stored in District and the physical-address field stays N/A.
Multiple source records for the same business are merged so a phone found in one source can enrich the record found in another source.
The app shows raw records returned by each source plus phone/address coverage.
Clean deployment
Delete uganda_leads.db before the first run if old test data is not needed. It will be recreated automatically.

requirements.txt contains Python packages. packages.txt contains only the Linux package needed for the optional Chromium headless-browser fallback.

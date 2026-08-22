# Propsearch.ae — Observed Site Structure

Investigated live on 2026-08-15 using a real browser (network inspection, DOM inspection,
raw-HTML fetch comparison). This document only records what was actually observed. Anything
not confirmed is marked as such.

## 0. High-level findings

- **Server-rendered HTML, no client-side API.** A raw `fetch()` of a page (no JS execution)
  returns the *complete* HTML with all listed items already present (verified: the JVC
  buildings page's raw HTML — fetched with plain `fetch()` — contained all building names,
  2.03 MB of HTML, no separate XHR calls fired even after the page finished loading real
  content). This means **httpx + BeautifulSoup is sufficient** for every page type discovered
  so far. Playwright is not required for the pages catalogued here.
- **No JSON-LD, no `__NEXT_DATA__`, no `__NUXT__`, no large inline JSON blobs.** Data must be
  parsed from rendered HTML text/structure, not from an embedded state object.
- **No `sitemap.xml`** (returns 404). `robots.txt` is `User-agent: * / Disallow:` (nothing
  blocked, no crawl-delay, no sitemap directive). Discovery must be done via link-following.
- **Coordinates** are embedded as a Google Maps Embed API iframe:
  `<iframe src="https://www.google.com/maps/embed/v1/place?key=...&q=LAT,LNG">` on building/
  development detail pages. Extract via regex on `q=` param. (The API key in that URL is
  Propsearch's own publishable embed key, not a secret of ours — do not log/exfiltrate it
  beyond what's needed to pull `q=`.)
- **A very light invisible reCAPTCHA Enterprise anchor loads on every page** (Google
  reCAPTCHA, `size=invisible`). It does not block normal page rendering or plain HTTP fetches
  of content — it appears to guard specific form actions (e.g. "Track Project"), not page
  reads. No challenge was ever presented during read-only browsing.
- Site is on Cloudflare-fronted infra typically, but no block/challenge page was encountered
  for either browser or plain WebFetch (non-browser HTTP) requests during this investigation.
  Scraper must still watch for 403/429/challenge HTML and back off per Section 12 of the
  brief — do not assume this will never happen at scale.

## 1. URL taxonomy

All Dubai real-estate content lives under `https://propsearch.ae/dubai/...` plus a few
sibling top-level sections. Confirmed path patterns:

| Pattern | Purpose | Confirmed example |
|---|---|---|
| `/dubai/area-guides` | Paginated master index of ALL Dubai areas/communities/districts | `/dubai/area-guides?page=2` |
| `/dubai/{slug}` | **Ambiguous**: an Area/Community page, OR a Development/Building page. Both use the same flat namespace. Disambiguate via the breadcrumb text ("Area Guides" vs "Building Guides") and the `Building type` field. | `/dubai/jumeirah-village-circle` (area), `/dubai/first-collection-jumeirah-village-circle` (building), `/dubai/cello` (multi-building development), `/dubai/cello-block-a` (individual building) |
| `/dubai/{area-slug}/buildings` | Full building/development directory for one area — **all developments rendered on a single page, no pagination observed** (886 developments for JVC, ~2 MB HTML, ~892 unique `/dubai/...` links) | `/dubai/jumeirah-village-circle/buildings` |
| `/dubai/{area-slug}/properties-buy-rent` | Live for-sale/for-rent listing counts (out of scope per brief — not a development/building record) | `/dubai/jumeirah-village-circle/properties-buy-rent` |
| `/dubai/{area-slug}/amenities` | Full amenities/POI directory for the area | `/dubai/jumeirah-village-circle/amenities` |
| `/dubai/{area-slug}/schools` | Nearby schools directory | `/dubai/jumeirah-village-circle/schools` |
| `/dubai/{area-slug}/things-to-do` | "What's On" content (events/attractions) | `/dubai/jumeirah-village-circle/things-to-do` |
| `/dubai-property-developers/{slug}` | Developer profile page | `/dubai-property-developers/nakheel` |
| `/dubai-construction-companies/{slug}` | Contractor/consultant profile page | `/dubai-construction-companies/norr-group-consultants-international-ltd` |
| `/dubai-properties-for-sale/by-location`, `/dubai-properties-to-rent/by-location`, `/dubai-commercial-properties-for-sale/by-location` | Live listing search sections — **out of scope** (this project scrapes development/building records, not live unit listings, per brief §21 comparison to Bayut/PF) | — |

**Discovery implication:** a URL allowlist cannot rely on a fixed path prefix to
distinguish "area" from "development/building" — both are `/dubai/{slug}`. The crawler
must fetch the page and classify it from content (breadcrumb second segment: "Area Guides"
vs "Building Guides"; presence/absence of a `Building type` field; presence of a
`SUB-COMMUNITIES` or `OVERVIEW ... building developments` block for areas).

## 2. Discovery graph (what actually links to what)

```
seed URL (e.g. /dubai/jumeirah-village-circle, or /dubai/area-guides for a full crawl)
  │
  ├─ /dubai/area-guides (paginated, ?page=N, 100 items/page, confirmed via "Next page"
  │    link href pattern; no total-page count is displayed — page until the "next" link
  │    is absent) → links to every top-level Area/Community page
  │
  ├─ Area page (/dubai/{slug})
  │    ├─ nav tabs → /properties-buy-rent, /amenities, /schools, /things-to-do, /buildings
  │    │    (these are REAL separate URLs, not JS-tab-only fragments — confirmed via
  │    │    anchor hrefs; some in-page nav items ALSO exist as same-page `#anchor` jump
  │    │    links, e.g. "Properties"/"Amenities"/"Schools" tabs on the Overview page
  │    │    itself scroll to sections already present in that page's HTML)
  │    ├─ SUB-COMMUNITIES block → links to child Area pages (/dubai/{child-slug}), each
  │    │    with its own status badge (Complete / Under development / Under development
  │    │    (Cancelled) / Under development (On hold) etc.) — this is how districts,
  │    │    sub-communities and master-development children are discovered
  │    ├─ inline "Iconic Buildings"/"Recently updated projects"/"Latest buildings"/
  │    │    "Latest areas" modules (seen on the Dubai home page) → more /dubai/{slug} links
  │    ├─ Developer link → /dubai-property-developers/{slug}
  │    └─ transaction rows → "Propsearch Guide" links back to /dubai/{slug} of the
  │         building/project the transaction occurred in (useful secondary discovery path)
  │
  ├─ /dubai/{area-slug}/buildings (single page, not paginated)
  │    └─ every development/building card links to /dubai/{slug} — this is the PRIMARY
  │         discovery source for developments within a known area. Card shows only
  │         {name, status icon+label}; full data requires visiting the detail page.
  │
  └─ Development/Building detail page (/dubai/{slug})
       ├─ if `Building type` = "Multi-building complex" (or similar): a "Sub-buildings"
       │    field lists child buildings by name with links → /dubai/{child-slug}
       │    (confirmed: Cello → Cello Block A, Cello Block B)
       ├─ if the page IS a sub-building: a "Master development" field links back to the
       │    parent development (confirmed: Cello Block A → Master development: Cello)
       ├─ Developer link → /dubai-property-developers/{slug}
       ├─ Architect/Contractor/Consultant links → /dubai-construction-companies/{slug}
       └─ transaction rows (same structure as area page)
```

### Pagination mechanism (confirmed)

Only the `/dubai/area-guides` directory listing was observed to paginate, via a plain
query-string pattern: `?page=2`, `?page=3`, ... Confirmed by reading the actual `href` of
the "Next page" (`chevron_right`) control — no JS/fetch/infinite-scroll involved. There is
no visible "last page" indicator, so the crawler must follow "next page" links until the
control is no longer present (or repeats/loops — track visited page URLs).

The per-area `/buildings` directory does **not** paginate — the entire list (hundreds of
entries) is rendered server-side on one response. Treat this as the general rule for
`/buildings` pages, but the crawler must still check for a pagination control defensively
(large areas could theoretically exceed a future page-size limit).

## 3. Area / Community page — fields observed

Example: `/dubai/jumeirah-village-circle`

- Breadcrumb: `Propsearch > Area Guides > {Name} Guide` — this breadcrumb text is the
  reliable signal that a `/dubai/{slug}` URL is an **Area**, not a Building.
- Title / name, one-line tagline/description
- `Updated {date}` — last-updated timestamp shown to users (not necessarily last scrape time)
- **"COMMUNITY" stat widget** (top of page) — this is **official DLD (Dubai Land
  Department) community-level data**, distinct from Propsearch's own per-development
  tallies below. Observed fields for JVC: a DLD community code (`681`), the DLD community
  name in Arabic and English (`Al Barsha South Fourth` — note this is the *broader* DLD
  administrative community JVC falls under, not JVC itself), and stats labelled `Buildings`,
  `Villas`, `Residential Units`, `Commercial Units`. **Do not conflate these with
  Propsearch's own development-count stats below** — store under a clearly-namespaced
  `dld_community_*` field group with the raw labels preserved.
- OVERVIEW section: `Area` (parent, e.g. "Dubai"), `Overview` (free text), `The developer`
  (master developer), `Also known as` (alias, e.g. "JVC"), `Amenities` (free text summary)
- `Timeline` — dated news/update snippets (headline + free text)
- `GUIDE` — long-form free-text description (history, character of the area)
- `LATEST TRANSACTIONS` — up to 50 recent DLD sale/mortgage transaction records rendered
  inline (see §5 Transactions below for field list); page states "Only a small sample...
  use Transaction Search in Pro Tools for the extended list" — Pro Tools is a paid/gated
  feature, out of scope
- `HISTORY` — long-form free text
- `TRANSPORT & ACCESS` — free text: commute times by car, airport proximity, road access,
  public transport
- `PROPERTIES ON THE MARKET` — live listing counts by bed count/type for buy/rent/short-term
  (out of scope — these are live listings, not development records, but the counts could
  optionally be captured as a snapshot metric on the area if useful later)
- `SUB-COMMUNITIES` — "There are N sub-communities in {Area}" + list of
  `{name, status-badge}` pairs, each linking to a child Area page
- `MASTERPLAN` — image gallery reference (masterplan images) — capture as document/photo
  metadata only (URL + label), no OCR/processing
- `CONSTRUCTION PHOTOS` — "Show all N photos" gallery reference
- `CONSTRUCTION HISTORY` → `Propsearch Research Data`: `Companies` (role → developer link),
  `Construction Photos` gallery, `Dubai Development Authority Data` → `Land Parcel Map`
  reference
- `{AREA} IN THE NEWS` — news headline + date items (continues past what was captured in
  this investigation; treat as a repeating news-item block)

A dedicated `/dubai/{slug}/buildings` sub-page additionally states, in plain text, the
Propsearch-native development-status breakdown for that area, e.g.:

> "There are currently 886 building developments in Jumeirah Village Circle. Of these, 456
> are complete, 24 are at the planning stage, 186 are at various stages of construction, and
> eight are either on-hold or facing construction delays. There were also 219 projects that
> have either been cancelled or never made it off the drawing board."

This sentence is the authoritative source for **Propsearch's own** area-level status
counts (as opposed to the DLD community widget numbers above) — parse it with a tolerant
regex but always prefer computing the same counts directly from the scraped development
records once a full crawl has completed (per brief: "Always calculate dashboard numbers
from scraped database records. Never hardcode them.") — this text is useful only as a
cross-check / progress indicator, not as the source of truth.

The `/buildings` page explicitly states a scope exclusion: *"the buildings on this page are
limited to residential and commercial buildings only. We do not include stations, bridges,
communication towers, municipality buildings, or government buildings such as palaces or
embassies."* — i.e. Propsearch's own counts already exclude non-real-estate structures.

It also includes an interactive map widget with its own count ("872 All buildings") that
does not exactly equal the "886 developments" figure — likely because a handful of
developments lack map coordinates. Both numbers are legitimate raw observations; do not
try to reconcile them, store both where encountered.

## 4. Development / Building detail page — fields observed

Two confirmed sub-types sharing one page template, distinguished by the `Building type`
field:

- **Single building** (e.g. `First Collection Jumeirah Village Circle` → `Building type:
  Hotel (Skyscraper)`)
- **Multi-building complex** (e.g. `Cello` → `Building type: Multi-building complex`),
  which additionally has a **`Sub-buildings`** field: free text + links naming each child
  building (e.g. "Cello Block A", "Cello Block B")
- **Individual sub-building of a complex** (e.g. `Cello Block A`) has a **`Master
  development`** field linking back to the parent, and an **`Other buildings`** field
  listing its siblings.

Breadcrumb for all of these: `Propsearch > Building Guides > {Name} Guide` — reliable
signal this `/dubai/{slug}` URL is a Building/Development, not an Area.

Confirmed fields (icon label → value), not all present on every page:

- Title, one-line description, `Updated {date}`
- `Building type` (e.g. Hotel (Skyscraper), Residential building, Multi-building complex,
  Villa, Townhouse, etc. — exact taxonomy not fully enumerated, capture raw string)
- `Status` (e.g. Complete, Under development) — also shown as an icon+label on list/card
  views with finer variants observed: `Complete`, `Under development`, `Under development
  (On hold)`, `Under development (Cancelled)`, `Planned`/`architecture` icon. Store the
  exact raw label as `raw_status`; derive `normalized_status` ourselves.
- `Storeys` (e.g. "42 storeys", or "21 storeys + 23 storeys" for a multi-building complex —
  free text, do not assume a single integer)
- **BUILDING SPECIFICATIONS** block:
  - `Area` — the immediate sub-community/district (e.g. "JVC District 14"), separate from
    the top-level Area
  - `Overview` — free text
  - `Master development` (sub-building pages only) — link to parent development
  - `Sub-buildings` (multi-building complex pages only) — free text + links to children
  - `The developer` — free text, "The project was/is a development by {Developer}" —
    contains a link to `/dubai-property-developers/{slug}`
  - `Timeline` — free text summary, e.g. "Construction began in June 2015 and was
    completed by June 2020."
  - `Units` — free text, e.g. **"The development contains a total of 491 units."** — this
    is the authoritative total-unit-count sentence; parse the integer but keep raw text.
    No bedroom-level breakdown was observed anywhere on this page — per brief, leave those
    fields NULL/UNKNOWN rather than inferring.
  - `Key dates` — free text combining estimated opening / actual completion
  - `The architect` — free text + link(s) to `/dubai-construction-companies/{slug}`
  - `The contractor` — free text + link(s) to `/dubai-construction-companies/{slug}`
    (building contractor, foundation/piling contractor, MEP consultant all appear as
    separate rows further down in `CONSTRUCTION HISTORY`)
  - `History` — free text (e.g. notes about a cancelled predecessor project on the same
    plot)
  - `Project value` — e.g. "AED 203,168,000 (USD 55.3m)" with a footnote that it's a
    developer-submitted pre-construction estimate — capture both currency figures
  - `Additional information` — a list of free-text bullet items (marketing copy, awards,
    F&B details, etc.) — capture as an array of strings, not structured data
  - `Amenities` (sub-building pages) — free text describing shared amenities
- `Timeline` (second occurrence) — a dated milestone/news feed specific to this project
  (month/year + free-text update), separate from the `MILESTONES` block below
- **INSIGHTS**: `Plot` (plot reference id, e.g. "JVC14AHRA005"), `Website` (official
  developer site link for the project, if any)
- **DUBAI LAND DEPARTMENT INFO** — section header; content not fully captured in this pass
  but appears to precede the transactions list
- **LATEST TRANSACTIONS** — same structure as the area page (see §5), scoped to this
  building/project
- **PROPERTIES ON THE MARKET** — live listing counts (out of scope, same as area page)
- **MILESTONES** — a clean structured list, confirmed labels: `First Trace`, `Estimated
  Start`, `Construction Started`, `Estimated Completion`, `Construction Finished` — each
  paired with a month/year value. This is the best structured source for construction
  dates; prefer it over parsing the free-text `Timeline`/`Key dates` sentences.
- **DESIGN STAGE** — "Show all N photos" gallery reference (concept design images)
- **CONSTRUCTION PHOTOS** — "Show all N photos" gallery reference
- **CONSTRUCTION HISTORY** → `Propsearch Research Data` → `Companies`: a role→link table,
  confirmed roles: `Developer`, `Architectural Consultant`, `Building Contractor`, `Piling
  Contractor`, `MEP Consultant` (roles vary per project) each linking to
  `/dubai-property-developers/{slug}` or `/dubai-construction-companies/{slug}`; also
  `Parcel ID` (numeric, e.g. "6817148") and `Plot Reference` (e.g. "JVC14AHRA005", matches
  the INSIGHTS `Plot` value)

### Coordinates

A Google Maps Embed iframe (`.../maps/embed/v1/place?key=...&q=LAT,LNG`) is present in the
page HTML for building/development pages carrying a location. Extract `LAT,LNG` from the
`q=` query parameter with a regex; do not rely on the browser DOM (this was found by
searching raw HTML, not a rendered DOM attribute).

### No embedded price-history chart data

The brief's guide text mentions "price history charts" for buildings; no inline chart
JSON/data was found on the pages inspected (only two small `<script>` tags totalling
~1.3 KB were present, neither containing chart series data, and no extra XHR fired). Charts
are most likely rendered as a static server-side image or require further JS interaction
not exercised in this pass. Do not build extraction logic for a chart data source that
was not actually observed — if this needs revisiting, re-inspect network traffic while
actively scrolling/interacting with a project page's chart area.

## 5. Transactions — fields observed (identical structure on Area pages and
   Building/Development pages)

Rendered inline as a list of DLD (Dubai Land Department) records, confirmed fields per
transaction:

- Date (e.g. "31 Jul 2026" summary / "31st Jul 2026" detail)
- Transaction Price (AED) and Price/sq.ft (AED) and Price/sq.m (AED)
- Size (sq. ft)
- Room description string, e.g. "1-bed flat, Binghatti Amber" / "3-bed villa" / "Studio
  hotel rooms, THE ONE" / "Office office, PRIME BUSINESS CENTER A"
- Transaction Type (e.g. Sale, Mortgage Registration, Pre-registration Sale, Delayed Sale,
  Delayed Mortgage) and Transaction Group (Sales / Mortgages)
- Transaction ID (DLD reference, e.g. "1-11-2026-23734")
- Property Type (Unit / Villa), Property Sub-type (Flat / Villa / Office / Hotel Rooms),
  Property Use (Residential / Commercial / Other)
- Registration Type (Ready property / Off-plan)
- Building Name (raw, as recorded by DLD — often differs in casing/formatting from
  Propsearch's own project name shown alongside)
- Room Type (Studio / 1-bed / 2-bed / 3-bed / Office, etc.)
- Parking (Yes/No)
- No. of Sellers, No. of Buyers
- Project (raw DLD project name, often upper-cased/differs from Propsearch's display name)
- Master Project (the area/community, e.g. "Jumeirah Village Circle")
- Area (the DLD community name, e.g. "Al Barsha South Fourth" — matches the COMMUNITY
  widget's community name on the area page, confirming that widget is DLD-sourced)
- "Propsearch Guide" — a link back to the Propsearch `/dubai/{slug}` guide page for this
  building/project (key for associating a transaction with our own Development/Building
  record)
- Fixed disclaimer footer text (buyer/seller identity not published)

Only a bounded recent sample (~50 on area pages) is rendered per page; there is no
pagination control observed for the transaction list itself, and a "Pro Tools /
Transaction Search" feature (gated, not investigated) provides the extended history —
treat that as out of scope.

## 6. Sub-communities / status badges — confirmed vocabulary

Observed raw status strings (icon + label) attached to sub-community and building list
entries:

- `check_circle Complete`
- `construction Under development`
- `architecture` (icon only seen in map-widget category filter, implies a "Planned" status
  category exists — confirm exact label text on a real planned-status card before
  finalizing the normalizer's mapping table)
- `motion_photos_pause Under development (On hold)`
- `do_disturb Under development (Cancelled)`

Store these verbatim as `raw_status`; the normalizer maps them to the brief's canonical
status set (`completed`, `under_construction`, `planned`, `announced`, `on_hold`,
`delayed`, `cancelled`, `other`).

## 7. Developer / Contractor profile pages

`/dubai-property-developers/{slug}` and `/dubai-construction-companies/{slug}` were linked
from building pages but not deep-inspected in this pass. They are reachable via the
`Companies` table on any building/development detail page and are a secondary discovery
source (not required to complete the primary Area → Development → Building graph). Treat
as optional enrichment; inspect further only if developer-entity data becomes a priority.

## 8. Respectful crawling notes specific to this site

- No `Crawl-delay` specified; robots.txt permits everything. Still apply a configurable
  delay + low concurrency per the brief — this is our own politeness policy, not a site
  requirement.
- Invisible reCAPTCHA Enterprise is present on every page load but did not block content
  reads in this investigation. If challenge pages start appearing under sustained crawling
  (403/429/Cloudflare interstitial HTML), the crawler must detect and back off/stop per
  brief §12 — do not attempt to solve or bypass it.
- Because `/dubai/{slug}` is used for both Areas and Developments/Buildings, the fetcher
  should not pre-classify by URL shape; classification happens after fetch by inspecting
  the breadcrumb ("Area Guides" vs "Building Guides") and structural cues.

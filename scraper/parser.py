"""HTML parsing for Propsearch pages, built against the actual markup documented in
PROPSEARCH_STRUCTURE.md (verified via raw `curl`-fetched HTML, not guessed selectors).

Two page templates share the `/dubai/{slug}` URL space: Area pages and
Development/Building pages. `classify_page()` tells them apart via the breadcrumb text.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from scraper import normalizer as norm
from scraper.models import (
    AmenityRecord, AreaPage, BuildingLinkRef, CompanyRef, DevelopmentPage, DocumentRef,
    LinkRef, MentionedPlace, MilestoneRecord, SchoolRecord, SubCommunityRef, TimelineUpdate,
    TransactionRecord,
)

BASE = "https://propsearch.ae"


# ---------------------------------------------------------------------------
# Generic structural helpers
# ---------------------------------------------------------------------------

def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _links_in(tag: Tag) -> list[LinkRef]:
    out = []
    for a in tag.find_all("a", href=True):
        href = urljoin(BASE, a["href"])
        out.append(LinkRef(url=href, text=_clean(a.get_text()) or ""))
    return out


def classify_page(soup: BeautifulSoup) -> str:
    """Return 'area', 'development', 'area_index', or 'unknown'.

    The breadcrumb (`Propsearch > Area Guides > {Name} Guide` or `Propsearch >
    Building Guides > {Name} Guide`) is the reliable signal — both page templates
    share the flat `/dubai/{slug}` URL space, so classification must happen on
    fetched content, not the URL shape (see PROPSEARCH_STRUCTURE.md §1).
    """
    if soup.find("a", href=re.compile(r"/dubai/area-guides$"), string=re.compile(r"Area Guides")):
        return "area"
    if soup.find("a", href=re.compile(r"/dubai/buildings$"), string=re.compile(r"Building Guides")):
        return "development"
    if soup.find(string=re.compile(r"Complete list of Dubai's geographical areas")):
        return "area_index"
    return "unknown"


def _find_spec_blocks(soup: BeautifulSoup) -> dict[str, Tag]:
    """Building-specifications style blocks:

        <div class="flex">
            <span class="material-icons-round ...">icon</span>
            <div>
                <div class="font-bold">Label</div>
                <div class="mb-8"><div>Value (may contain links)</div></div>
            </div>
        </div>

    Returns {label_text: value_container_tag}. Used on both Area and Development pages.
    """
    out: dict[str, Tag] = {}
    for label_div in soup.find_all("div", class_=lambda c: c and c.split() == ["font-bold"]):
        label = _clean(label_div.get_text())
        if not label:
            continue
        value_div = label_div.find_next_sibling("div")
        if value_div is None:
            continue
        out[label] = value_div
    return out


def _hero_image_url(soup: BeautifulSoup, name: str | None) -> str | None:
    """The page's own primary photo: an `<img alt="{exact page name}">` (verified
    against real cached HTML for both area and development pages). Deliberately NOT
    "the first <img> on the page" — most images on a page are shared site-wide nav
    thumbnails for unrelated areas/categories that happen to repeat on every page;
    matching on the exact alt text is what actually scopes this to the entity itself.
    """
    if not name:
        return None
    img = soup.find("img", alt=re.compile(rf"^\s*{re.escape(name)}\s*$", re.IGNORECASE))
    if img is None or not img.get("src"):
        return None
    return urljoin(BASE, img["src"])


def _find_quick_facts(soup: BeautifulSoup) -> dict[str, str]:
    """The three-box quick-facts row (Building type / Status / Storeys) at the top of a
    development page: label in `.font-bold.leading-snug`, value in the following
    `.mb-2` sibling.
    """
    out: dict[str, str] = {}
    for label_span in soup.find_all("div", class_=lambda c: c and "font-bold" in c.split() and "leading-snug" in c.split()):
        label = _clean(label_span.get_text())
        value_div = label_span.find_next_sibling("div")
        if label and value_div is not None:
            out[label] = _clean(value_div.get_text().replace("\n", " ")) or ""
    return out


def _text_value_pairs(container: Tag, label_class_hint: str = "text-gray") -> dict[str, str]:
    """Generic `<div>Label</div><div>Value</div>` pair scanner used for the DLD
    COMMUNITY stat widget and the transaction detail grid, where the label div's class
    contains a gray/muted-text marker and the very next sibling div holds the value.
    """
    out: dict[str, str] = {}
    for label_div in container.find_all("div"):
        classes = label_div.get("class") or []
        if not any(label_class_hint in c for c in classes):
            continue
        value_div = label_div.find_next_sibling("div")
        if value_div is None:
            continue
        label = _clean(label_div.get_text())
        value = _clean(value_div.get_text())
        if label:
            out[label] = value or ""
    return out


# ---------------------------------------------------------------------------
# Transactions (shared structure: area pages and development pages)
# ---------------------------------------------------------------------------

def parse_transactions(soup: BeautifulSoup, source_url: str) -> list[TransactionRecord]:
    records: list[TransactionRecord] = []
    for panel in soup.find_all("div", class_=lambda c: c and "zena-expander" in c.split()):
        detail_grid = panel.find_parent("div", class_=lambda c: c and "relative" in c.split())
        scope = detail_grid or panel
        pairs = _text_value_pairs(scope, label_class_hint="text-gray-500")
        guide_link = None
        guide_a = scope.find("a", href=re.compile(r"/dubai/"))
        # The Propsearch Guide link sits in its own centered block; find the one under
        # the "Propsearch Guide" caption specifically.
        caption = scope.find(string=re.compile(r"^Propsearch Guide$"))
        if caption:
            caption_tag = caption.find_parent("div")
            if caption_tag:
                sib = caption_tag.find_next_sibling("div")
                if sib:
                    a = sib.find("a", href=True)
                    if a:
                        guide_link = urljoin(BASE, a["href"])
        if guide_link is None and guide_a is not None:
            guide_link = urljoin(BASE, guide_a["href"])

        price_span = panel.find("span", class_="price-val")
        price_aed = float(price_span["data-orig"]) if price_span and price_span.get("data-orig") else None
        size_span = panel.find("span", class_=lambda c: c and "ps-area-size-switcher" in c.split())
        size_sqft = float(size_span["data-sqft"].replace(",", "")) if size_span and size_span.get("data-sqft") else None

        room_desc = None
        summary_rows = panel.find_all("div", class_=lambda c: c and "text-nowrap" in c.split() and "overflow-ellipsis" in c.split())
        if summary_rows:
            room_desc = _clean(summary_rows[0].get_text())

        if not pairs and price_aed is None:
            continue

        date_raw = pairs.get("Date")
        records.append(TransactionRecord(
            transaction_id=pairs.get("Transaction ID"),
            transaction_date_raw=date_raw,
            transaction_date=norm.parse_transaction_date(date_raw),
            price_aed=price_aed,
            price_per_sqft_aed=norm.parse_money(pairs.get("Price/sq. ft")),
            price_per_sqm_aed=norm.parse_money(pairs.get("Price/sq m")),
            size_sqft=size_sqft,
            room_type=pairs.get("Room Type"),
            property_type=pairs.get("Property Type"),
            property_subtype=pairs.get("Property Sub-type"),
            property_use=pairs.get("Property Use"),
            registration_type=pairs.get("Registration Type"),
            transaction_type=pairs.get("Transaction Type"),
            transaction_group=pairs.get("Transaction Group"),
            building_name_raw=pairs.get("Building Name"),
            project_raw=pairs.get("Project"),
            master_project_raw=pairs.get("Master Project"),
            area_raw=pairs.get("Area"),
            num_sellers=norm.parse_int(pairs.get("No. of Sellers")),
            num_buyers=norm.parse_int(pairs.get("No. of Buyers")),
            parking=pairs.get("Parking"),
            propsearch_guide_url=guide_link,
            source_url=source_url,
        ))
    return records


# ---------------------------------------------------------------------------
# Building-directory cards (used by /dubai/{area}/buildings AND sub-community grids)
# ---------------------------------------------------------------------------

def parse_building_cards(soup: BeautifulSoup) -> list[BuildingLinkRef]:
    seen: dict[str, BuildingLinkRef] = {}
    for name_div in soup.find_all("div", class_=lambda c: c and "line-clamp-2" in c.split() and "font-bold" in c.split()):
        anchor = name_div.find_parent("a", href=True, title=True)
        if anchor is None:
            continue
        url = urljoin(BASE, anchor["href"])
        if "/dubai/" not in url:
            continue
        name = _clean(anchor.get("title")) or _clean(name_div.get_text())
        status_text = None
        status_container = anchor.find_next_sibling("div")
        if status_container is not None:
            icon = status_container.find("span")
            if icon is not None and icon.next_sibling:
                status_text = _clean(str(icon.next_sibling))
            else:
                status_text = _clean(status_container.get_text())
        if name and url not in seen:
            seen[url] = BuildingLinkRef(name=name, url=url, raw_status=status_text)
    return list(seen.values())


def parse_subcommunities(soup: BeautifulSoup) -> list[SubCommunityRef]:
    out: list[SubCommunityRef] = []
    header = soup.find(["h2", "h3"], string=re.compile(r"^Sub-communities$"))
    scope = soup
    if header is not None:
        block = header.find_parent("div", class_=lambda c: c and "ps-3-col-block" in c.split())
        if block is not None:
            nxt = block.find_next_sibling("div")
            if nxt is not None:
                nxt2 = nxt.find_next_sibling("div")
                scope = nxt2 or nxt
    seen: dict[str, SubCommunityRef] = {}
    for anchor in scope.find_all("a", class_=lambda c: c and "group" in c.split(), href=True):
        url = urljoin(BASE, anchor["href"])
        if "/dubai/" not in url:
            continue
        name_div = anchor.find("div", class_=lambda c: c and "font-bold" in c.split())
        if name_div is None:
            continue
        name = _clean(name_div.get_text())
        status_span = anchor.find("span", class_="material-icons")
        status_text = None
        if status_span is not None and status_span.next_sibling:
            status_text = _clean(str(status_span.next_sibling))
        img = anchor.find("img")
        image_url = urljoin(BASE, img["src"]) if img is not None and img.get("src") else None
        if name and url not in seen:
            seen[url] = SubCommunityRef(name=name, url=url, raw_status=status_text, image_url=image_url)
    return list(seen.values())


def parse_documents(soup: BeautifulSoup) -> list[DocumentRef]:
    docs: list[DocumentRef] = []
    label_map = {
        "MASTERPLAN": "masterplan",
        "CONSTRUCTION PHOTOS": "construction_photos",
        "DESIGN STAGE": "design_stage",
    }
    for header in soup.find_all(["h2", "h3"]):
        label = _clean(header.get_text())
        if not label:
            continue
        key = label.upper()
        if key not in label_map:
            continue
        block = header.find_parent("div", class_=lambda c: c and "ps-3-col-block" in c.split())
        photo_count = None
        photo_urls: list[str] = []
        if block is not None:
            desc_block = block.find_next_sibling("div")
            content_block = desc_block.find_next_sibling("div") if desc_block is not None else None
            if content_block is not None:
                m = re.search(r"Show all (\d+) photos?", content_block.get_text())
                if m:
                    photo_count = int(m.group(1))
                # The actual gallery: a PhotoSwipe widget whose <a href> IS the
                # full-resolution image URL (verified against real cached HTML —
                # "Construction Photos"/"Design Stage" sections use this markup).
                for a in content_block.find_all(
                    "a", class_=lambda c: c and "zena-photoswipe-item" in c.split(), href=True
                ):
                    photo_urls.append(urljoin(BASE, a["href"]))
        docs.append(DocumentRef(doc_type=label_map[key], label=label, photo_count=photo_count,
                                 photo_urls=photo_urls))
    return docs


_NON_CATEGORY_HEADERS = {
    "overview", "latest transactions", "sub-communities", "masterplan",
    "construction photos", "construction history", "properties on the market",
    "milestones", "design stage",
}


def _category_for(tag: Tag) -> str | None:
    header = tag.find_previous(["h2", "h3"], class_="ps-crosshead")
    if header is None:
        return None
    text = _clean(header.get_text())
    if text and text.lower() in _NON_CATEGORY_HEADERS:
        return None
    return text


def parse_amenities_page(html: str, soup: BeautifulSoup | None = None) -> list[AmenityRecord]:
    """Amenities/POI directory (/dubai/{area}/amenities). Two markup variants were
    observed for a listed outlet (see PROPSEARCH_STRUCTURE.md): a "featured" inline
    form (`NAME, <a>Building</a>` in one div) and a "list" form (a `.font-bold` name
    div followed by a sibling div with the building link + floor/location text). Both
    are handled; category comes from the nearest preceding `h2.ps-crosshead`.
    """
    if soup is None:
        soup = BeautifulSoup(html, "lxml")
    out: list[AmenityRecord] = []
    seen: set[tuple] = set()
    for link in soup.find_all("a", class_="ps-link", href=True):
        parent_div = link.find_parent("div")
        if parent_div is None:
            continue
        building_name = _clean(link.get_text())
        prev_bold = parent_div.find_previous_sibling(
            "div", class_=lambda c: c and "font-bold" in c.split()
        )
        name = None
        distance_text = None
        # "list" variant: name lives in a preceding sibling div, this div only holds
        # the building link + trailing location text (e.g. "Street level").
        if prev_bold is not None and prev_bold.parent is parent_div.parent:
            name = _clean(prev_bold.get_text())
            trailing = parent_div.get_text(" ", strip=True)
            trailing = trailing.replace(building_name or "", "", 1).lstrip(", ").strip()
            distance_text = trailing or None
        else:
            # "featured" variant: "Name, <a>Building</a>" in the same div.
            full_text = parent_div.get_text(" ", strip=True)
            if building_name and full_text.endswith(building_name):
                name = full_text[: -len(building_name)].rstrip(", ").strip()
        if not name:
            continue
        category = _category_for(link) or "Uncategorized"
        key = (name, category, building_name)
        if key in seen:
            continue
        seen.add(key)
        out.append(AmenityRecord(name=name, category=category, building_context=building_name,
                                  distance_text=distance_text))
    return out


def parse_schools_page(html: str, soup: BeautifulSoup | None = None) -> list[SchoolRecord]:
    """Nearby-schools directory (/dubai/{area}/schools). Each entry: a
    `.font-bold.mb-4` name div followed by `<span>Label: </span>Value` fact rows
    (Location/Distance/Annual fees/Government rating/Parent rating).
    """
    if soup is None:
        soup = BeautifulSoup(html, "lxml")
    out: list[SchoolRecord] = []
    for name_div in soup.find_all("div", class_=lambda c: c and "font-bold" in c.split() and "mb-4" in c.split()):
        name = _clean(name_div.get_text())
        if not name:
            continue
        facts: dict[str, str] = {}
        sib = name_div.find_next_sibling("div")
        while sib is not None:
            span = sib.find("span")
            if span is None:
                break
            label = _clean(span.get_text())
            if label and label.endswith(":"):
                value = _clean(sib.get_text().replace(span.get_text(), "", 1))
                facts[label.rstrip(":")] = value
            sib = sib.find_next_sibling("div")
            if sib is not None and "text-sm mb-3" not in " ".join(sib.get("class") or []):
                break
        curriculum = _category_for(name_div)
        out.append(SchoolRecord(
            name=name,
            curriculum=curriculum,
            rating=facts.get("Government rating"),
            distance_text=facts.get("Distance"),
            fees_text=facts.get("Annual fees"),
            location_text=facts.get("Location"),
        ))
    return out


def parse_milestones(soup: BeautifulSoup) -> list[MilestoneRecord]:
    out = []
    header = soup.find("div", class_=lambda c: c and "font-medium" in c.split() and "mb-4" in c.split(),
                        string=re.compile(r"Milestones$"))
    if header is None:
        return out
    box = header.find_parent("div", class_=lambda c: c and "border" in c.split() and "rounded-xl" in c.split())
    if box is None:
        return out
    for row in box.find_all("div", class_=lambda c: c and "grid-cols-2" in c.split()):
        cells = row.find_all("div", recursive=False)
        if len(cells) != 2:
            continue
        label = _clean(cells[0].get_text())
        value = _clean(cells[1].get_text())
        if label and value:
            out.append(MilestoneRecord(label=label, date_raw=value, date_parsed=norm.parse_fuzzy_date(value)))
    return out


def companies_from_specs(specs: dict[str, Tag]) -> list[CompanyRef]:
    """Company involvement, derived from the free-text BUILDING SPECIFICATIONS fields
    ("The developer" / "The architect" / "The contractor"), which are confirmed present
    in plain (unauthenticated) HTTP responses.

    The site also has a separate structured "Companies Directory" table (with finer
    roles like Piling Contractor / MEP Consultant) under CONSTRUCTION HISTORY, but that
    table was observed served as a locked/gated teaser ("N Companies Involved", no
    actual links) for anonymous requests — see PROPSEARCH_STRUCTURE.md §4. We do not
    guess at markup for content we couldn't confirm unlocked; this function only uses
    fields verified to be public.
    """
    role_map = {"The developer": "Developer", "The architect": "Architect", "The contractor": "Contractor"}
    out: list[CompanyRef] = []
    for field, role in role_map.items():
        tag = specs.get(field)
        if tag is None:
            continue
        for link in _links_in(tag):
            out.append(CompanyRef(role=role, name=link.text, url=link.url))
    return out


def parse_timeline_updates(soup: BeautifulSoup) -> list[TimelineUpdate]:
    """The per-project dated milestone/news feed rendered as month-letter + year-digit
    columns followed by a `<p>` description (see PROPSEARCH_STRUCTURE.md Timeline).
    """
    out = []
    for row in soup.find_all("div", class_=lambda c: c and "flex-col" in c.split() and "lg:flex-row" in c.split()):
        letters_col = row.find("div", class_=lambda c: c and "select-none" in c.split())
        desc_col = row.find("div", class_=lambda c: c and c.split() == ["grow"])
        if letters_col is None or desc_col is None:
            continue
        # Each character (month letters, year digits) sits in its own <div>, so joining
        # via stripped_strings avoids get_text()'s inter-tag whitespace ("J a n 2 0 2 1").
        joined = "".join(letters_col.stripped_strings)
        raw = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", joined) or None
        desc = _clean(desc_col.get_text())
        if raw and desc:
            out.append(TimelineUpdate(date_raw=raw, date_parsed=norm.parse_fuzzy_date(raw), description=desc))
    return out


_TRANSPORT_HEADING_RE = re.compile(r"^Transport\s*&\s*Access$", re.IGNORECASE)


def parse_mentioned_places(soup: BeautifulSoup) -> list[MentionedPlace]:
    """Internal-link place mentions from the "Transport & Access" prose block (present
    on both area and development pages — see PROPSEARCH_STRUCTURE.md). This section is
    narrative text ("22 minutes to Dubai Mall...") with occasional links to other
    propsearch.ae pages, not a structured POI widget — there is no distance/coordinate
    data to extract per mention beyond what's literally written, so this captures the
    mention (name, link, surrounding sentence, subsection) and nothing fabricated.

    Structure (verified against real cached HTML): an `h2.ps-crosshead` heading reading
    "Transport & Access", followed by a sibling block containing a
    `.ps-prose` container. Inside it, `div.ps-h3` subsection labels (e.g. "Commute
    times by car", "Road access") precede `<p>` prose paragraphs holding the links.
    """
    out: list[MentionedPlace] = []
    heading = soup.find(["h2", "h3"], class_="ps-crosshead", string=_TRANSPORT_HEADING_RE)
    if heading is None:
        return out
    block = heading.find_parent("div", class_=lambda c: c and "ps-3-col-block" in c.split())
    if block is None:
        return out
    prose_block = block.find_next_sibling(
        "div", class_=lambda c: c and "ps-3-col-block" in c.split()
    )
    if prose_block is None:
        return out
    container = prose_block.find("div", class_=lambda c: c and "ps-prose" in c.split())
    if container is None:
        return out

    section: str | None = None
    seen: set[tuple[str, str, str | None]] = set()
    for child in container.find_all(recursive=False):
        classes = child.get("class") or []
        if child.name == "div" and "ps-h3" in classes:
            section = _clean(child.get_text())
            continue
        if child.name != "p":
            continue
        context_sentence = _clean(child.get_text())
        for link in _links_in(child):
            if not link.text:
                continue
            key = (link.text, link.url, section)
            if key in seen:
                continue
            seen.add(key)
            out.append(MentionedPlace(
                name=link.text, linked_url=link.url,
                context_sentence=context_sentence, section=section,
            ))
    return out


# ---------------------------------------------------------------------------
# Area page
# ---------------------------------------------------------------------------

def parse_area_page(html: str, url: str, soup: BeautifulSoup | None = None) -> AreaPage:
    if soup is None:
        soup = BeautifulSoup(html, "lxml")
    name_tag = soup.find("h1")
    name = _clean(name_tag.get_text()) if name_tag else url

    page = AreaPage(url=url, name=name)

    specs = _find_spec_blocks(soup)
    if "Area" in specs:
        page.parent_area = _clean(specs["Area"].get_text())
    if "Overview" in specs:
        page.overview_text = _clean(specs["Overview"].get_text())
    if "The developer" in specs:
        page.developer_raw = _clean(specs["The developer"].get_text())
        links = _links_in(specs["The developer"])
        if links:
            page.developer_link = links[0]
    if "Also known as" in specs:
        page.also_known_as = _clean(specs["Also known as"].get_text())

    # DLD COMMUNITY stat widget: a `.select-none` box with two child boxes (community
    # code + bilingual community name), followed by a sibling grid of 4 stat cards
    # (Buildings/Villas/Residential Units/Commercial Units). See PROPSEARCH_STRUCTURE.md.
    community_label = soup.find(string=re.compile(r"^\s*COMMUNITY\s*$"))
    if community_label:
        widget = community_label.find_parent("div", class_=lambda c: c and "select-none" in c.split())
        if widget is not None:
            nums = widget.find_all("div", class_=lambda c: c and "font-transport-medium" in c.split())
            if len(nums) >= 1:
                page.dld_community_code = _clean(nums[0].get_text())
            if len(nums) >= 2:
                page.dld_community_name_en = _clean(nums[1].get_text())
            arabic_names = widget.find_all("div", class_=lambda c: c and "font-din" in c.split())
            if arabic_names:
                page.dld_community_name_ar = _clean(arabic_names[-1].get_text())
            # widget's parent (`.flex-none`) is a sibling of the stat-cards container
            widget_wrap = widget.find_parent("div")
            stat_scope = widget_wrap.find_next_sibling("div") if widget_wrap is not None else None
            if stat_scope is not None:
                stat_pairs = _text_value_pairs(stat_scope, label_class_hint="text-gray-700")
                page.dld_buildings = norm.parse_int(stat_pairs.get("Buildings"))
                page.dld_villas = norm.parse_int(stat_pairs.get("Villas"))
                page.dld_residential_units = norm.parse_int(stat_pairs.get("Residential Units"))
                page.dld_commercial_units = norm.parse_int(stat_pairs.get("Commercial Units"))

    # Propsearch's own development-status summary sentence (only present on the
    # /buildings sub-page, but harmless to look for here too)
    summary_match = soup.find(string=re.compile(r"currently \d[\d,]* building developments"))
    if summary_match:
        text = str(summary_match) + " " + str(summary_match.find_next(string=True) or "")
        page.propsearch_dev_summary_raw = _clean(text)
        m = re.search(r"currently ([\d,]+) building developments", text)
        if m:
            page.propsearch_dev_total = int(m.group(1).replace(",", ""))
        m = re.search(r"([\d,]+) are complete", text)
        if m:
            page.propsearch_dev_completed = int(m.group(1).replace(",", ""))
        m = re.search(r"([\d,]+) are at the planning stage", text)
        if m:
            page.propsearch_dev_planned = int(m.group(1).replace(",", ""))
        m = re.search(r"([\d,]+) are at various stages of construction", text)
        if m:
            page.propsearch_dev_under_construction = int(m.group(1).replace(",", ""))
        m = re.search(r"(\w+) are either on-hold", text)
        if m:
            page.propsearch_dev_on_hold = _word_to_int(m.group(1))
    cancelled_match = soup.find(string=re.compile(r"[\d,]+ projects that.*(cancelled|drawing board)"))
    if cancelled_match:
        m = re.search(r"([\d,]+) projects", str(cancelled_match))
        if m:
            page.propsearch_dev_cancelled = int(m.group(1).replace(",", ""))

    page.subcommunities = parse_subcommunities(soup)
    page.transactions = parse_transactions(soup, url)
    page.documents = parse_documents(soup)
    page.latitude, page.longitude = norm.parse_coordinates(html)
    page.hero_image_url = _hero_image_url(soup, page.name)

    updated = soup.find(string=re.compile(r"^Updated "))
    if updated:
        page.updated_label = _clean(str(updated))

    return page


_WORD_NUMS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
              "eight": 8, "nine": 9, "ten": 10}


def _word_to_int(word: str) -> int | None:
    if word.isdigit():
        return int(word)
    return _WORD_NUMS.get(word.lower())


# ---------------------------------------------------------------------------
# Buildings directory listing (/dubai/{area}/buildings)
# ---------------------------------------------------------------------------

def parse_buildings_listing(html: str, soup: BeautifulSoup | None = None) -> tuple[list[BuildingLinkRef], AreaPage | None]:
    """Returns (building cards, partial area-stat info parsed from the overview text).

    Reuses a caller-supplied `soup` when given — this page can be ~2MB of HTML (JVC:
    886 developments in one response) and re-parsing it multiple times is the single
    biggest cost in a full crawl, so every caller in this codebase threads the same
    parsed tree through rather than calling BeautifulSoup() again.
    """
    if soup is None:
        soup = BeautifulSoup(html, "lxml")
    cards = parse_building_cards(soup)
    stub = parse_area_page(html, url="", soup=soup)
    return cards, stub


# ---------------------------------------------------------------------------
# Development / Building detail page
# ---------------------------------------------------------------------------

def parse_development_page(html: str, url: str, soup: BeautifulSoup | None = None) -> DevelopmentPage:
    if soup is None:
        soup = BeautifulSoup(html, "lxml")
    name_tag = soup.find("h1")
    name = _clean(name_tag.get_text()) if name_tag else url
    dev = DevelopmentPage(url=url, name=name)

    quick = _find_quick_facts(soup)
    dev.building_type_raw = quick.get("Building type")
    dev.raw_status = quick.get("Status")
    dev.storeys_raw = quick.get("Storeys")
    if dev.building_type_raw and "multi-building" in dev.building_type_raw.lower():
        dev.is_multi_building = True

    desc_tag = soup.find("h1")
    if desc_tag:
        following_p = desc_tag.find_next(string=True)
    specs = _find_spec_blocks(soup)

    if "Area" in specs:
        dev.area_raw = _clean(specs["Area"].get_text())
    if "Overview" in specs:
        dev.overview_text = _clean(specs["Overview"].get_text())
    if "The developer" in specs:
        dev.developer_raw = _clean(specs["The developer"].get_text())
        links = _links_in(specs["The developer"])
        if links:
            dev.developer_link = links[0]
    if "Master development" in specs:
        links = _links_in(specs["Master development"])
        if links:
            dev.master_development_link = links[0]
    if "Sub-buildings" in specs:
        dev.sub_building_links = _links_in(specs["Sub-buildings"])
        dev.is_multi_building = True
    if "Other buildings" in specs:
        dev.other_building_links = _links_in(specs["Other buildings"])
    if "Timeline" in specs:
        dev.timeline_summary_raw = _clean(specs["Timeline"].get_text())
    if "Units" in specs:
        text = _clean(specs["Units"].get_text())
        dev.total_units, dev.total_units_raw = norm.parse_total_units(text)
    if "Key dates" in specs:
        dev.key_dates_raw = _clean(specs["Key dates"].get_text())
    if "History" in specs:
        dev.history_text = _clean(specs["History"].get_text())
    if "Project value" in specs:
        text = _clean(specs["Project value"].get_text())
        dev.project_value_raw = text
        dev.project_value_aed, dev.project_value_usd = norm.parse_project_value(text)
    if "Amenities" in specs:
        dev.amenities_text = _clean(specs["Amenities"].get_text())

    additional = []
    for bullet in soup.find_all("div", class_=lambda c: c and "ps-loc-fact-body" in c.split()):
        p = bullet.find("p")
        text = _clean(p.get_text()) if p else _clean(bullet.get_text())
        if text:
            additional.append(text)
    dev.additional_info = additional

    insights_website = soup.find(string=re.compile(r"^\s*Website\s*$"))
    if insights_website:
        label_div = insights_website.find_parent("div")
        if label_div is not None:
            value_div = label_div.find_next_sibling("div")
            if value_div is not None:
                a = value_div.find("a", href=True)
                if a:
                    dev.official_website = urljoin(BASE, a["href"])

    plot_label = soup.find(string=re.compile(r"^\s*Plot\s*$"))
    if plot_label:
        label_div = plot_label.find_parent("div")
        if label_div is not None:
            value_div = label_div.find_next_sibling("div")
            if value_div is not None:
                text = _clean(value_div.get_text())
                m = re.search(r"plot\s+([A-Za-z0-9\-]+)", text or "", re.I)
                dev.plot_reference = m.group(1) if m else text

    dev.companies = companies_from_specs(specs)
    dev.milestones = parse_milestones(soup)
    dev.timeline_updates = parse_timeline_updates(soup)
    dev.documents = parse_documents(soup)
    dev.transactions = parse_transactions(soup, url)
    dev.latitude, dev.longitude = norm.parse_coordinates(html)
    dev.hero_image_url = _hero_image_url(soup, dev.name)

    updated = soup.find(string=re.compile(r"^Updated "))
    if updated:
        dev.updated_label = _clean(str(updated))

    return dev

"""Plain dataclasses for parsed page content. These sit between `parser.py` (HTML ->
dataclass) and `storage.py` (dataclass -> SQLite upsert). Keeping them as simple
dataclasses (not an ORM) matches the brief's "don't over-engineer" instruction.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LinkRef:
    url: str
    text: str


@dataclass
class SubCommunityRef:
    name: str
    url: str
    raw_status: str | None = None
    image_url: str | None = None


@dataclass
class TransactionRecord:
    transaction_id: str | None
    transaction_date_raw: str | None
    transaction_date: str | None
    price_aed: float | None
    price_per_sqft_aed: float | None
    price_per_sqm_aed: float | None
    size_sqft: float | None
    room_type: str | None
    property_type: str | None
    property_subtype: str | None
    property_use: str | None
    registration_type: str | None
    transaction_type: str | None
    transaction_group: str | None
    building_name_raw: str | None
    project_raw: str | None
    master_project_raw: str | None
    area_raw: str | None
    num_sellers: int | None
    num_buyers: int | None
    parking: str | None
    propsearch_guide_url: str | None
    source_url: str = ""


@dataclass
class CompanyRef:
    role: str
    name: str
    url: str | None


@dataclass
class MilestoneRecord:
    label: str
    date_raw: str
    date_parsed: str | None


@dataclass
class TimelineUpdate:
    date_raw: str
    date_parsed: str | None
    description: str


@dataclass
class DocumentRef:
    doc_type: str  # masterplan | construction_photos | design_stage | land_parcel_map
    label: str
    photo_count: int | None = None
    url: str | None = None
    photo_urls: list[str] = field(default_factory=list)


@dataclass
class AmenityRecord:
    name: str
    category: str
    building_context: str | None = None
    distance_text: str | None = None


@dataclass
class MentionedPlace:
    """An internally-linked place name mentioned in an area's Transport & Access
    prose (e.g. "22 minutes to Dubai Mall") — captured as a mention with its
    surrounding sentence, not a fabricated structured POI record. Propsearch does
    not expose malls/metro/hospitals as structured distance/coordinate data; this
    is the honest, verified-against-real-HTML version of that.
    """
    name: str
    linked_url: str
    context_sentence: str | None
    section: str | None  # e.g. "Commute times by car", "Public transport"


@dataclass
class SchoolRecord:
    name: str
    curriculum: str | None = None
    rating: str | None = None
    distance_text: str | None = None
    fees_text: str | None = None
    location_text: str | None = None


@dataclass
class AreaPage:
    url: str
    name: str
    description: str | None = None
    parent_area: str | None = None
    also_known_as: str | None = None
    overview_text: str | None = None
    developer_raw: str | None = None
    developer_link: LinkRef | None = None
    dld_community_code: str | None = None
    dld_community_name_en: str | None = None
    dld_community_name_ar: str | None = None
    dld_buildings: int | None = None
    dld_villas: int | None = None
    dld_residential_units: int | None = None
    dld_commercial_units: int | None = None
    propsearch_dev_summary_raw: str | None = None
    propsearch_dev_total: int | None = None
    propsearch_dev_completed: int | None = None
    propsearch_dev_under_construction: int | None = None
    propsearch_dev_planned: int | None = None
    propsearch_dev_on_hold: int | None = None
    propsearch_dev_cancelled: int | None = None
    subcommunities: list[SubCommunityRef] = field(default_factory=list)
    transactions: list[TransactionRecord] = field(default_factory=list)
    documents: list[DocumentRef] = field(default_factory=list)
    amenities: list[AmenityRecord] = field(default_factory=list)
    schools: list[SchoolRecord] = field(default_factory=list)
    history_text: str | None = None
    transport_text: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    updated_label: str | None = None
    hero_image_url: str | None = None


@dataclass
class BuildingLinkRef:
    """One row from an area's /buildings directory listing."""
    name: str
    url: str
    raw_status: str | None


@dataclass
class DevelopmentPage:
    url: str
    name: str
    description: str | None = None
    building_type_raw: str | None = None
    is_multi_building: bool = False
    raw_status: str | None = None
    storeys_raw: str | None = None
    area_raw: str | None = None  # immediate sub-community/district text
    overview_text: str | None = None
    developer_raw: str | None = None
    developer_link: LinkRef | None = None
    master_development_link: LinkRef | None = None
    sub_building_links: list[LinkRef] = field(default_factory=list)
    other_building_links: list[LinkRef] = field(default_factory=list)
    total_units: int | None = None
    total_units_raw: str | None = None
    timeline_summary_raw: str | None = None
    key_dates_raw: str | None = None
    history_text: str | None = None
    project_value_aed: float | None = None
    project_value_usd: float | None = None
    project_value_raw: str | None = None
    additional_info: list[str] = field(default_factory=list)
    amenities_text: str | None = None
    plot_reference: str | None = None
    parcel_id: str | None = None
    official_website: str | None = None
    companies: list[CompanyRef] = field(default_factory=list)
    milestones: list[MilestoneRecord] = field(default_factory=list)
    timeline_updates: list[TimelineUpdate] = field(default_factory=list)
    documents: list[DocumentRef] = field(default_factory=list)
    transactions: list[TransactionRecord] = field(default_factory=list)
    latitude: float | None = None
    longitude: float | None = None
    updated_label: str | None = None
    hero_image_url: str | None = None


@dataclass
class FetchResult:
    url: str
    final_url: str
    status_code: int | None
    html: str | None
    error: str | None
    blocked: bool = False

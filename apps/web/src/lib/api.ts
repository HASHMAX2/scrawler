const BASE = "/api";

async function get<T>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
  const qs = params
    ? "?" + Object.entries(params)
        .filter(([, v]) => v !== undefined && v !== null && v !== "")
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
        .join("&")
    : "";
  const res = await fetch(`${BASE}${path}${qs}`);
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${path}: ${body}`);
  }
  return res.json();
}

export interface Overview {
  period: string;
  current_range: [string, string];
  previous_range: [string, string];
  data_range: [string, string];
  sales: {
    count: number; value: number | null; avg_price: number | null; median_price: number | null; median_psf: number | null;
    value_formatted: string; avg_price_formatted: string; change_pct: number | null; value_change_pct: number | null; confidence: string;
  };
  rentals: { count: number; avg_rent: number | null; median_rent: number | null; change_pct: number | null; confidence: string };
  estimated_gross_yield_pct: number | null;
  best_selling_unit_type: { bedroom: string; count: number } | null;
  highest_rental_activity_area: { community: string; count: number } | null;
  highest_transaction_growth_area: { community: string; current: number; previous: number; change_pct: number | null } | null;
  largest_incoming_supply: { area: string; units: number } | null;
  supply: { active_projects: number; under_construction: number; known_residential_units: number | null };
}

export interface CommunityListItem {
  community_key: string; community_name: string; has_scraped_profile: boolean;
  sales_count: number; sales_value: number | null; median_price: number | null; median_psf: number | null;
  rental_count: number; median_rent: number | null; estimated_gross_yield_pct: number | null;
  hero_image_url: string | null;
}

export interface CommunityList { period: string; page: number; page_size: number; total: number; items: CommunityListItem[] }

export interface AreaRollupStats {
  sales_count: number; sales_value: number | null; median_price: number | null;
  rental_count: number; median_rent: number | null; estimated_gross_yield_pct: number | null;
}
export interface AreaDataSource { sales: "dld_direct" | "project_matched"; rentals: "dld_direct" | "project_matched" }

export interface AreaListItem extends AreaRollupStats {
  area_id: number; name: string; hero_image_url: string | null; also_known_as: string | null;
  child_count: number; descendant_count: number;
  project_matched_stats: AreaRollupStats;
  data_source: AreaDataSource;
}
export interface AreaListResponse { period: string; items: AreaListItem[] }

export interface AreaChildItem extends AreaRollupStats {
  area_id: number; name: string; hero_image_url: string | null; community_key: string; child_count: number;
  project_matched_stats: AreaRollupStats;
  data_source: AreaDataSource;
}

export interface AreaProjectItem {
  master_project_id: number; name: string; slug: string; developer_name: string | null; building_count: number;
  sales_count: number; median_price: number | null; median_psf: number | null;
  rental_count: number; median_rent: number | null; estimated_gross_yield_pct: number | null;
}
export interface AreaProjectsResponse { period: string; items: AreaProjectItem[] }

export interface AreaDetailResponse {
  area_id: number; name: string; area_type: string; community_key: string; has_dld_link: boolean;
  breadcrumb: { area_id: number; name: string }[];
  profile: AreaProfile | null;
  livability: LivabilityPanel | null;
  period: string;
  own_stats: AreaRollupStats & { data_source: AreaDataSource };
  own_project_matched_stats: AreaRollupStats;
  subtree_stats: AreaRollupStats & { data_source: AreaDataSource };
  subtree_project_matched_stats: AreaRollupStats;
  child_count: number;
  children: AreaChildItem[];
}

export interface AreaProfile {
  description: string | null; also_known_as: string | null; hero_image_url: string | null;
  dld_community_name_en: string | null; dld_buildings: number | null; dld_villas: number | null;
  dld_residential_units: number | null; dld_commercial_units: number | null;
}

export interface SchoolItem { name: string; curriculum: string; rating: string | null; distance_text: string | null; fees_text: string | null }

export interface LivabilityPanel {
  amenity_counts: { category: string; count: number }[];
  total_amenities: number;
  school_curriculum_counts: { curriculum: string; count: number }[];
  total_schools: number;
  top_schools: SchoolItem[];
}

export interface CommunityDetail {
  community_key: string; community_name: string; has_scraped_profile: boolean;
  data_source: "dld_direct" | "project_matched"; period: string;
  sales: { count: number; value: number | null; median_price: number | null; median_psf: number | null; confidence: string };
  rentals: { count: number; median_rent: number | null; renewals: number | null; new_contracts: number | null; confidence: string };
  estimated_gross_yield_pct: number | null;
  bedroom_demand: {
    sales: { bedroom: string; count: number; share_pct: number | null }[];
    rentals: { bedroom: string; count: number; share_pct: number | null; median_rent: number | null }[];
  };
  top_projects: { name: string; sales_count: number; sales_value: number }[];
  top_developers: { name: string; project_count: number }[];
  upcoming_supply_units: number | null;
  oversupply_risk: OversupplyRisk;
  area_profile: AreaProfile | null;
  livability: LivabilityPanel | null;
}

export interface OversupplyRisk {
  risk: "low" | "moderate" | "high" | "very_high" | "insufficient_data";
  ratio: number | null;
  incoming_units: number | null;
  trailing_annualized_demand: number | null;
  note?: string;
}

export interface LiquidityScore {
  score: number;
  transaction_count: number;
  months_span: number;
  monthly_rate: number;
  consistency: number;
  formula: string;
}

export interface BreakdownResponse {
  period: string; by: string;
  items: { label: string; count: number; value?: number; median_price?: number; median_psf?: number; median_rent?: number; median_rent_psf?: number; share_pct: number | null }[];
}

export interface TrendPoint { date: string; count: number; value?: number; median_price?: number; median_psf?: number; median_rent?: number; renewals?: number; new_contracts?: number }
export interface TrendResponse { period: string; granularity: string; points: TrendPoint[] }

export interface DemandMatrix {
  period: string; metric: string; bedrooms: string[];
  matrix: { community_key: string; community_name: string; total: number; values: Record<string, number> }[];
}

export interface UnitTypeItem {
  bedroom: string; sales_count: number; sales_share_pct: number | null; sales_change_pct: number | null;
  median_price: number | null; median_psf: number | null; rental_count: number; rental_share_pct: number | null;
  median_rent: number | null; estimated_gross_yield_pct: number | null; sales_confidence: string; rental_confidence: string;
}
export interface UnitTypesResponse { period: string; community_key: string | null; items: UnitTypeItem[] }

export interface ScrapedCrossCheckItem {
  development_name: string; scraped_transaction_count: number; scraped_median_price: number | null;
  dld_transaction_count: number; dld_median_price: number | null; median_price_diff_pct: number | null;
}
export interface ScrapedCrossCheck {
  total_scraped_transactions: number; matched_to_development: number; developments_with_dld_counterpart: number;
  projects_compared: ScrapedCrossCheckItem[]; note: string;
}

export interface DataQuality {
  area_match_confidence: Record<string, number>;
  project_match_confidence: Record<string, number>;
  files_imported: { file_path: string; dataset_type: string; row_count: number; imported_at: string | null; status: string }[];
  unmatched_project_sales_rows: number; unmatched_project_rental_rows: number;
  missing_project_sales_rows: number; missing_project_rental_rows: number;
  invalid_price_rows: number; invalid_rent_rows: number;
  scraped_cross_check: ScrapedCrossCheck;
}

export interface ConstructionWatchItem {
  change_id: number; development_id: number; development_name: string; area_name: string | null;
  field_name: string; old_value: string | null; new_value: string | null; detected_at: string;
  master_project_slug: string | null;
}
export interface ConstructionWatchResponse {
  items: ConstructionWatchItem[];
  field_counts: Record<string, number>;
  flipped_to_completed_total: number;
  watched_fields: string[];
}

export interface ExplorerResponse<T> { page: number; page_size: number; total: number; items: T[] }
export interface SaleRow { sale_id: number; instance_date: string; community: string; project: string | null; property_type: string; bedroom: string | null; price: number; area_sqm: number; price_per_sqft: number | null; is_offplan: boolean }
export interface RentalRow { rental_id: number; registration_date: string; community: string; project: string | null; property_type: string; bedroom: string | null; annual_rent: number; area_sqm: number; rent_per_sqft: number | null; is_renewal: boolean }

export interface MapDevelopment {
  development_id: number; name: string; lat: number; lng: number; area_name: string | null; status: string | null;
  developer_name: string | null; total_units: number | null; hero_image_url: string | null; sales_count: number;
}

export interface ProjectListItem {
  project_id: number; name: string; matched_development_id: number | null; developer_name: string | null;
  sales_count: number; sales_value: number | null; rental_count: number;
  building_slug: string | null; master_slug: string | null; hero_image_url: string | null;
}
export interface DeveloperListItem { developer_id: number; name: string; project_count: number; sales_count: number; sales_value: number; market_share_pct: number | null }

export interface SupplyResponse {
  status_breakdown: Record<string, number>;
  unit_supply_populated_developments: number;
  known_units: Record<string, number | null> | null;
  upcoming_by_area: { area: string | null; projects: number; units: number | null }[];
  upcoming_by_developer: { developer: string; projects: number }[];
}

export interface OpportunityItem { community_key: string; community_name: string; why: string; [key: string]: unknown }
export interface OpportunitiesResponse {
  period: string; methodology: string;
  high_yield_high_demand: OpportunityItem[];
  rising_sales_momentum: OpportunityItem[];
  rental_growth_outpacing_price: OpportunityItem[];
}

export interface AreaGrowthItem {
  community_key: string; community_name: string;
  current_count: number; previous_count: number; change_pct: number;
  median_value: number | null; momentum: "accelerating" | "stable" | "slowing" | "insufficient_data";
}
export interface HotProject { project_name: string; current_count: number; trailing_monthly_avg: number; ratio: number }
export interface DeveloperMomentumItem { developer_name: string; current_count: number; previous_count: number; change_pct: number }
export interface PulseResponse {
  period: string; min_sample: number;
  fastest_growing_areas: AreaGrowthItem[];
  cooling_areas: AreaGrowthItem[];
  hot_projects: HotProject[];
  rental_hotspots: AreaGrowthItem[];
  developer_momentum: DeveloperMomentumItem[];
}

export interface MarketSignal {
  category: string; text: string;
  evidence: Record<string, unknown> & { community?: string; community_key?: string; area?: string; project?: string };
}
export interface SignalsResponse { period: string; min_sample: number; signals: MarketSignal[] }

export interface DecisionEngineResult {
  community_key: string; community_name: string;
  median_price: number | null; median_rent: number | null;
  estimated_gross_yield_pct: number | null; psf_growth_pct: number | null;
  sales_count: number; rental_count: number;
  liquidity: LiquidityScore; oversupply_risk: OversupplyRisk;
  score: number;
  score_breakdown: { components: Record<string, number | null>; weights: Record<string, number>; oversupply_penalty: number };
  why: string; risks: string[]; missing_data: string[];
}
export interface DecisionEngineResponse {
  period: string;
  profile: Record<string, string | number | null>;
  methodology: string;
  excluded_insufficient_data: number;
  results: DecisionEngineResult[];
}
export interface DecisionEngineProfile {
  period?: string; budget_max?: number; areas?: string; property_type?: string; bedroom?: string;
  ready_offplan?: "ready" | "offplan" | "either";
  priority?: "rental_income" | "capital_appreciation" | "liquidity" | "balanced";
  risk_tolerance?: "low" | "medium" | "high";
  limit?: number;
}

export interface SearchSuggestItem {
  id: number; kind: "master" | "building"; name: string; subtitle: string; slug: string; master_slug: string | null;
}
export interface SearchSuggestResponse { query: string; items: SearchSuggestItem[] }

export interface ProjectBuildingRef { project_id: number; name: string; building_label: string | null; slug: string; grouping_method: string }

export interface ConstructionMilestone { label: string; date_raw: string | null; date_parsed: string | null }
export interface ConstructionUpdate { date_raw: string | null; date_parsed: string | null; description: string }
export interface ConstructionCompany { role: string; name: string; url: string | null }
export interface ProjectDocumentGroup { doc_type: string; total_photos: number; cover_photo_urls: string[] }

export interface ScrapedEnrichment {
  source_development_id: number;
  source_building_name: string | null;
  hero_image_url: string | null;
  building_type: string | null;
  status: string | null;
  raw_status: string | null;
  storeys: string | null;
  total_units: number | null;
  total_units_raw: string | null;
  project_value_aed: number | null;
  project_value_usd: number | null;
  official_website: string | null;
  plot_reference: string | null;
  overview_text: string | null;
  construction_start_date: string | null;
  estimated_completion_date: string | null;
  actual_completion_date: string | null;
  first_trace_date: string | null;
  latitude: number | null;
  longitude: number | null;
  is_multi_building: boolean;
  companies: ConstructionCompany[];
  milestones: ConstructionMilestone[];
  updates: ConstructionUpdate[];
  documents: ProjectDocumentGroup[];
}

export interface MasterProjectDetail {
  master_project_id: number; slug: string; name: string;
  developer_name: string | null; area_name: string | null;
  building_count: number; needs_review: boolean;
  buildings: ProjectBuildingRef[];
  selected_building: { project_id: number; name: string; building_label: string | null; slug: string } | null;
  scraped_enrichment: ScrapedEnrichment | null;
  period: string;
  filters: { unit_type: string | null; transaction_type: string | null };
  kpis: {
    sales: {
      count: number; count_change_pct: number | null; value: number | null; avg_price: number | null; median_price: number | null;
      avg_psf: number | null; median_psf: number | null; count_30d: number; count_90d: number; count_6m: number; confidence: string;
    };
    rentals: {
      count: number; count_change_pct: number | null; avg_rent: number | null; median_rent: number | null; avg_rent_psf: number | null;
      new_count: number | null; renewal_count: number | null; confidence: string;
    };
    market: {
      sales_velocity_per_day: number; rental_velocity_per_day: number; avg_ticket_size: number | null;
      estimated_gross_yield_pct: number | null;
      price_trend_pct: number | null; price_trend: string; rental_trend_pct: number | null; rental_trend: string;
      liquidity: LiquidityScore;
    };
  };
  trends: {
    sales: { date: string; count: number; value: number | null; avg_psf: number | null; avg_price: number | null }[];
    rentals: { date: string; count: number; avg_rent: number | null; avg_rent_psf: number | null }[];
  };
  unit_type_performance: {
    bedroom: string; sales_count: number; sales_value: number | null; avg_price: number | null; median_price: number | null; avg_psf: number | null;
    rental_count: number; avg_rent: number | null; median_rent: number | null; estimated_gross_yield_pct: number | null;
    sales_share_pct: number | null; rental_share_pct: number | null;
  }[];
  building_performance: {
    project_id: number; name: string; building_label: string | null; slug: string; grouping_method: string; has_scraped_profile: boolean;
    sales_count: number; sales_value: number | null; avg_price: number | null; avg_psf: number | null;
    rental_count: number; avg_rent: number | null; estimated_gross_yield_pct: number | null; last_transaction_date: string | null;
  }[];
  sales_vs_rentals: {
    sales_demand_count: number; rental_demand_count: number; rental_to_sales_ratio: number | null;
    estimated_gross_yield_pct: number | null;
    most_liquid_unit_type: string | null; most_rented_unit_type: string | null; highest_volume_unit_type: string | null;
  };
  data_quality: { grouping_method_summary: Record<string, number>; matched_scraped_buildings: number; total_buildings: number };
}

export interface ReelMetric {
  label: string; value: number | string | null; format: string; tone?: string | null; note?: string | null;
}
export interface ReelBreakdownRow { label: string; value: number | string | null; secondary?: number | null }
export interface ReelEntity {
  id: string; label: string; subtitle?: string | null; metrics: ReelMetric[];
  sampleSize: { sales: number; rentals: number };
  breakdown?: Record<string, ReelBreakdownRow[]>;
}
export interface ReelVerdictRow { dimension: string; winner: string | null; detail: string }
export interface ReelManifestItem {
  id: number; title: string; category: string; franchise: string | null;
  analyticalAngle: string; requiredSources: string[]; outputType: string; resolver: string;
  status: "ready" | "partial" | "external"; missingSources: string[]; sourceLabels: string[];
}
export interface ReelListResponse {
  total: number; filtered: number;
  counts: { ready: number; partial: number; external: number };
  categories: { name: string; count: number; readyCount: number }[];
  items: ReelManifestItem[];
}
export interface ReelFranchise { name: string; description: string; count: number; readyCount: number }
export interface ReelRunResult {
  reel: ReelManifestItem; status: string; question: string; period: string;
  entities: ReelEntity[]; verdict: ReelVerdictRow[] | null;
  reelReadyFacts: string[]; whatIsInteresting: string | null; caveat: string; sources: string[];
  priceBandDepth?: ReelBreakdownRow[];
  availableProjects?: string[];
  claim?: string;
}
export interface ReadyToMakeCard {
  finding: string; entity: string | null; communityKey: string | null; magnitude: number;
  suggestedReels: { id: number; title: string; category: string; status: string }[];
}

export const api = {
  overview: (period: string, community_key?: string) => get<Overview>("/overview", { period, community_key }),
  communities: (period: string, page: number, page_size: number, sort?: string, search?: string) =>
    get<CommunityList>("/communities", { period, page, page_size, sort, search }),
  communityDetail: (key: string, period: string) => get<CommunityDetail>(`/communities/${encodeURIComponent(key)}`, { period }),
  compare: (keys: string[], period: string) => get<{ period: string; items: CommunityDetail[] }>("/compare", { keys: keys.join(","), period }),
  salesBreakdown: (by: string, period: string, community_key?: string, limit = 20) =>
    get<BreakdownResponse>("/sales/breakdown", { by, period, community_key, limit }),
  salesTrend: (period: string, granularity: string, community_key?: string) =>
    get<TrendResponse>("/sales/trend", { period, granularity, community_key }),
  rentalsBreakdown: (by: string, period: string, community_key?: string, limit = 20) =>
    get<BreakdownResponse>("/rentals/breakdown", { by, period, community_key, limit }),
  rentalsTrend: (period: string, granularity: string, community_key?: string) =>
    get<TrendResponse>("/rentals/trend", { period, granularity, community_key }),
  demandMatrix: (period: string, metric: string, top_n_communities = 15) =>
    get<DemandMatrix>("/rentals/demand-matrix", { period, metric, top_n_communities }),
  unitTypes: (period: string, community_key?: string) => get<UnitTypesResponse>("/unit-types", { period, community_key }),
  dataQuality: () => get<DataQuality>("/data-quality"),
  reviewQueue: (entity_type: string, limit = 100) => get<{ entity_type: string; items: { raw_key: string; raw_name: string; match_score: number }[] }>("/data-quality/review-queue", { entity_type, limit }),
  explorerSales: (page: number, page_size: number, filters: Record<string, string | undefined>) =>
    get<ExplorerResponse<SaleRow>>("/explorer/sales", { page, page_size, ...filters }),
  explorerRentals: (page: number, page_size: number, filters: Record<string, string | undefined>) =>
    get<ExplorerResponse<RentalRow>>("/explorer/rentals", { page, page_size, ...filters }),
  mapDevelopments: () => get<{ items: MapDevelopment[] }>("/map/developments"),
  projects: (search: string | undefined, period: string, limit = 50) => get<{ period: string; items: ProjectListItem[] }>("/projects", { search, period, limit }),
  developers: (period: string, limit = 50) => get<{ period: string; items: DeveloperListItem[] }>("/developers", { period, limit }),
  supply: () => get<SupplyResponse>("/supply"),
  opportunities: (period: string) => get<OpportunitiesResponse>("/opportunities", { period }),
  pulse: (period: string, limit = 5) => get<PulseResponse>("/pulse", { period, limit }),
  signals: (period: string, limit_per_category = 5) => get<SignalsResponse>("/signals", { period, limit_per_category }),
  decisionEngine: (profile: DecisionEngineProfile) =>
    get<DecisionEngineResponse>("/decision-engine", {
      period: profile.period, budget_max: profile.budget_max, areas: profile.areas,
      property_type: profile.property_type, bedroom: profile.bedroom, ready_offplan: profile.ready_offplan,
      priority: profile.priority, risk_tolerance: profile.risk_tolerance, limit: profile.limit,
    }),
  searchSuggest: (q: string, limit = 12) => get<SearchSuggestResponse>("/search/suggest", { q, limit }),
  masterProjectDetail: (slug: string, period: string, building_slug?: string, unit_type?: string, transaction_type?: string) =>
    get<MasterProjectDetail>(`/projects/master/${encodeURIComponent(slug)}`, { period, building_slug, unit_type, transaction_type }),
  constructionWatch: (field?: string, limit = 50) => get<ConstructionWatchResponse>("/construction-watch", { field, limit }),
  areas: (period: string) => get<AreaListResponse>("/areas", { period }),
  areaDetail: (areaId: number | string, period: string) => get<AreaDetailResponse>(`/areas/${areaId}`, { period }),
  areaProjects: (areaId: number | string, period: string, limit = 12) =>
    get<AreaProjectsResponse>(`/areas/${areaId}/projects`, { period, limit }),
  reels: (params: { category?: string; franchise?: string; status?: string; source?: string; output?: string; search?: string }) =>
    get<ReelListResponse>("/reels", params),
  reelFranchises: () => get<{ items: ReelFranchise[] }>("/reels/franchises"),
  reelDetail: (id: number) => get<ReelManifestItem>(`/reels/${id}`),
  runReel: (id: number, params: Record<string, string | number | undefined>) => get<ReelRunResult>(`/reels/${id}/run`, params),
  readyToMake: (period: string, limit = 12) => get<{ period: string; items: ReadyToMakeCard[] }>("/reels/meta/opportunities", { period, limit }),
};

export async function refreshData(): Promise<unknown> {
  const res = await fetch(`${BASE}/import/refresh`, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function uploadFile(file: File): Promise<unknown> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/import/upload`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { MapContainer, TileLayer, CircleMarker, Popup } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { api } from "../lib/api";
import { ErrorState, LoadingSkeleton } from "../components/ui";

const STATUS_COLORS: Record<string, string> = {
  completed: "#5a9c6e",
  under_construction: "#c98a4b",
  planned: "#7a8fa6",
  announced: "#7a8fa6",
  on_hold: "#c9974b",
  delayed: "#c9974b",
  cancelled: "#b05c5c",
  other: "#6b6259",
};
const DEFAULT_COLOR = "#6b6259";

export function MapPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ["map-developments"], queryFn: () => api.mapDevelopments() });
  const [fullscreen, setFullscreen] = useState(false);

  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFullscreen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [fullscreen]);

  if (isLoading) return <LoadingSkeleton rows={6} />;
  if (error) return <ErrorState message={(error as Error).message} />;
  if (!data) return null;

  const maxSales = Math.max(1, ...data.items.map((d) => d.sales_count));
  const statuses = Object.keys(STATUS_COLORS);

  const legend = (
    <div className="flex flex-wrap gap-3">
      {statuses.map((s) => (
        <span key={s} className="flex items-center gap-1.5 text-[10px] text-[var(--text-muted)]">
          <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ background: STATUS_COLORS[s] }} />
          {s.replace("_", " ")}
        </span>
      ))}
    </div>
  );

  const markers = data.items.map((d) => {
    const color = (d.status && STATUS_COLORS[d.status]) ?? DEFAULT_COLOR;
    return (
      <CircleMarker
        key={d.development_id}
        center={[d.lat, d.lng]}
        radius={4 + 10 * (d.sales_count / maxSales)}
        pathOptions={{ color, fillColor: color, fillOpacity: 0.6 }}
      >
        <Popup>
          <div className="text-sm space-y-1">
            {d.hero_image_url && <img src={d.hero_image_url} alt={d.name} className="w-full h-24 object-cover rounded" loading="lazy" />}
            <div className="font-semibold">{d.name}</div>
            <div>{d.area_name}</div>
            <div>{d.developer_name ?? "Unknown developer"}</div>
            <div>{d.status?.replace("_", " ") ?? "Status unknown"}</div>
            <div>{d.sales_count} sales this period</div>
          </div>
        </Popup>
      </CircleMarker>
    );
  });

  if (fullscreen) {
    return (
      <div className="fixed inset-0 z-50 bg-[var(--bg)] flex flex-col p-4 gap-3">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold">Map</h1>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">{data.items.length} developments with known coordinates.</p>
            <div className="mt-1.5">{legend}</div>
          </div>
          <button
            onClick={() => setFullscreen(false)}
            className="shrink-0 text-xs font-medium border border-[var(--border)] rounded-full px-4 py-2 hover:border-[var(--accent)] hover:text-[var(--accent)] transition-colors bg-[var(--surface)]"
          >
            ✕ Exit Fullscreen
          </button>
        </div>
        <div className="flex-1 rounded-lg overflow-hidden border border-[var(--border)]">
          <MapContainer center={[25.15, 55.25]} zoom={11} style={{ height: "100%", width: "100%" }}>
            <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
            {markers}
          </MapContainer>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-semibold">Map</h1>
          <p className="text-sm text-[var(--text-muted)] mt-0.5">
            {data.items.length} developments with known coordinates. Marker size reflects sales activity this period, color reflects construction status. No
            community boundary data is available yet, so this shows point markers rather than a choropleth.
          </p>
          <div className="mt-2">{legend}</div>
        </div>
        <button
          onClick={() => setFullscreen(true)}
          className="shrink-0 text-xs font-medium border border-[var(--border)] rounded-full px-4 py-2 hover:border-[var(--accent)] hover:text-[var(--accent)] transition-colors"
        >
          ⛶ Fullscreen
        </button>
      </div>
      <div className="rounded-lg overflow-hidden border border-[var(--border)]" style={{ height: 600 }}>
        <MapContainer center={[25.15, 55.25]} zoom={11} style={{ height: "100%", width: "100%" }}>
          <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
          {markers}
        </MapContainer>
      </div>
    </div>
  );
}

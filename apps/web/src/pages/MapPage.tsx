import { useQuery } from "@tanstack/react-query";
import { MapContainer, TileLayer, CircleMarker, Popup } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { api } from "../lib/api";
import { ErrorState, LoadingSkeleton } from "../components/ui";

export function MapPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ["map-developments"], queryFn: () => api.mapDevelopments() });

  if (isLoading) return <LoadingSkeleton rows={6} />;
  if (error) return <ErrorState message={(error as Error).message} />;
  if (!data) return null;

  const maxSales = Math.max(1, ...data.items.map((d) => d.sales_count));

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold">Map</h1>
        <p className="text-xs text-[var(--text-muted)]">
          {data.items.length} developments with known coordinates. Marker size reflects sales activity this period. No community boundary data is
          available yet, so this shows point markers rather than a choropleth.
        </p>
      </div>
      <div className="rounded-lg overflow-hidden border border-[var(--border)]" style={{ height: 600 }}>
        <MapContainer center={[25.15, 55.25]} zoom={11} style={{ height: "100%", width: "100%" }}>
          <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
          {data.items.map((d) => (
            <CircleMarker
              key={d.development_id}
              center={[d.lat, d.lng]}
              radius={4 + 10 * (d.sales_count / maxSales)}
              pathOptions={{ color: "#c98a4b", fillColor: "#c98a4b", fillOpacity: 0.6 }}
            >
              <Popup>
                <div className="text-sm">
                  <div className="font-semibold">{d.name}</div>
                  <div>{d.area_name}</div>
                  <div>{d.developer_name ?? "Unknown developer"}</div>
                  <div>{d.status ?? "Status unknown"}</div>
                  <div>{d.sales_count} sales this period</div>
                </div>
              </Popup>
            </CircleMarker>
          ))}
        </MapContainer>
      </div>
    </div>
  );
}

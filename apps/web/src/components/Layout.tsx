import { NavLink, Outlet } from "react-router-dom";
import { PERIOD_OPTIONS, useFilters } from "../state/FilterContext";
import { Select } from "./ui";

const NAV_SECTIONS: { title: string; items: { to: string; label: string }[] }[] = [
  { title: "", items: [{ to: "/", label: "Overview" }] },
  {
    title: "Market Intelligence",
    items: [
      { to: "/sales", label: "Sales" },
      { to: "/rentals", label: "Rentals" },
      { to: "/unit-types", label: "Unit Types" },
      { to: "/communities", label: "Communities" },
      { to: "/projects", label: "Projects" },
      { to: "/developers", label: "Developers" },
      { to: "/supply", label: "Supply" },
      { to: "/construction-watch", label: "Construction Watch" },
    ],
  },
  {
    title: "",
    items: [
      { to: "/compare", label: "Compare" },
      { to: "/opportunities", label: "Opportunities" },
      { to: "/signals", label: "Market Signals" },
      { to: "/decision-engine", label: "Decision Engine" },
      { to: "/map", label: "Map" },
    ],
  },
  {
    title: "",
    items: [
      { to: "/explorer", label: "Data Explorer" },
      { to: "/import", label: "Import Data" },
      { to: "/data-quality", label: "Data Quality" },
    ],
  },
];

export function Layout() {
  const { period, setPeriod } = useFilters();
  return (
    <div className="flex h-full">
      <aside className="w-56 shrink-0 border-r border-[var(--border)] bg-[var(--surface)] flex flex-col">
        <div className="px-4 py-4 border-b border-[var(--border)]">
          <div className="text-sm font-semibold tracking-wide text-[var(--text)]">DUBAI RE INTELLIGENCE</div>
          <div className="text-[10px] text-[var(--text-muted)] mt-0.5">Data + Analytics Terminal</div>
        </div>
        <nav className="flex-1 overflow-y-auto py-2">
          {NAV_SECTIONS.map((section, i) => (
            <div key={i} className="mb-3">
              {section.title && (
                <div className="px-4 py-1 text-[10px] uppercase tracking-wider text-[var(--text-muted)]">{section.title}</div>
              )}
              {section.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === "/"}
                  className={({ isActive }) =>
                    `block px-4 py-1.5 text-sm ${isActive ? "bg-[var(--accent-soft)] text-[var(--accent)] border-r-2 border-[var(--accent)]" : "text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-white/5"}`
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
      </aside>
      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-14 border-b border-[var(--border)] flex items-center justify-between px-6 bg-[var(--surface)]">
          <div className="text-xs text-[var(--text-muted)]">Dubai Residential Market</div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-[var(--text-muted)]">Period</span>
            <Select value={period} onChange={(v) => setPeriod(v as never)} options={PERIOD_OPTIONS} />
          </div>
        </header>
        <main className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

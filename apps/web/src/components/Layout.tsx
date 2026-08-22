import { useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { PERIOD_OPTIONS, useFilters } from "../state/FilterContext";
import { useTheme } from "../state/ThemeContext";
import { Select } from "./ui";

const NAV_SECTIONS: { title: string; items: { to: string; label: string }[] }[] = [
  { title: "", items: [{ to: "/", label: "Overview" }] },
  {
    title: "Market",
    items: [
      { to: "/sales", label: "Sales" },
      { to: "/rentals", label: "Rentals" },
      { to: "/unit-types", label: "Unit Types" },
      { to: "/supply", label: "Supply" },
      { to: "/construction-watch", label: "Construction" },
    ],
  },
  {
    title: "Explore",
    items: [
      { to: "/areas", label: "Areas" },
      { to: "/communities", label: "Communities" },
      { to: "/projects", label: "Projects" },
      { to: "/developers", label: "Developers" },
      { to: "/map", label: "Map" },
    ],
  },
  {
    title: "Intelligence",
    items: [
      { to: "/intelligence-map", label: "Intelligence Map" },
      { to: "/reels", label: "Reels" },
      { to: "/opportunities", label: "Opportunities" },
      { to: "/signals", label: "Market Signals" },
      { to: "/compare", label: "Compare" },
      { to: "/decision-engine", label: "Decision Engine" },
    ],
  },
  {
    title: "Data",
    items: [
      { to: "/explorer", label: "Data Explorer" },
      { to: "/import", label: "Import Data" },
      { to: "/data-quality", label: "Data Quality" },
    ],
  },
];

function ViewSwitcher() {
  const location = useLocation();
  const navigate = useNavigate();
  const isIntel = location.pathname.startsWith("/intelligence-map");
  return (
    <div className="flex items-center rounded-full border border-[var(--border)] p-0.5 bg-[var(--surface-2)]">
      <button
        onClick={() => navigate("/")}
        className={`text-xs font-medium px-3.5 py-1.5 rounded-full transition-colors ${!isIntel ? "bg-[var(--accent)] text-[var(--bg)]" : "text-[var(--text-muted)] hover:text-[var(--text)]"}`}
      >
        Dashboard
      </button>
      <button
        onClick={() => navigate("/intelligence-map")}
        className={`text-xs font-medium px-3.5 py-1.5 rounded-full transition-colors ${isIntel ? "bg-[var(--accent)] text-[var(--bg)]" : "text-[var(--text-muted)] hover:text-[var(--text)]"}`}
      >
        Intelligence Map
      </button>
    </div>
  );
}

function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  return (
    <button
      onClick={toggleTheme}
      title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
      className="w-8 h-8 rounded-full border border-[var(--border)] flex items-center justify-center text-xs text-[var(--text-muted)] hover:text-[var(--text)] hover:border-[var(--accent)]/50 transition-colors"
    >
      {theme === "dark" ? "☾" : "☀"}
    </button>
  );
}

export function Layout() {
  const { period, setPeriod } = useFilters();
  const location = useLocation();
  const isIntel = location.pathname.startsWith("/intelligence-map");
  const [collapsed, setCollapsed] = useState(false);
  const sidebarCollapsed = isIntel || collapsed;

  return (
    <div className="flex h-full">
      <aside
        className={`shrink-0 border-r border-[var(--border)] bg-[var(--surface)] flex flex-col transition-[width] duration-300 ${sidebarCollapsed ? "w-14" : "w-56"}`}
      >
        <div className={`px-4 py-4 border-b border-[var(--border)] flex items-center ${sidebarCollapsed ? "justify-center px-0" : "justify-between"}`}>
          {!sidebarCollapsed && (
            <div>
              <div className="text-sm font-semibold tracking-wide text-[var(--text)]" style={{ fontFamily: "var(--font-display)" }}>
                DUBAI RE INTELLIGENCE
              </div>
              <div className="text-[10px] text-[var(--text-muted)] mt-0.5">Data + Analytics Terminal</div>
            </div>
          )}
          {!isIntel && (
            <button
              onClick={() => setCollapsed((c) => !c)}
              className="text-[var(--text-muted)] hover:text-[var(--text)] text-xs w-6 h-6 flex items-center justify-center rounded hover:bg-[var(--hover-overlay)]"
              title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            >
              {collapsed ? "»" : "«"}
            </button>
          )}
        </div>
        <nav className="flex-1 overflow-y-auto py-2">
          {NAV_SECTIONS.map((section, i) => (
            <div key={i} className="mb-3">
              {section.title && !sidebarCollapsed && (
                <div className="px-4 py-1 text-[10px] uppercase tracking-wider text-[var(--text-muted)]">{section.title}</div>
              )}
              {section.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === "/"}
                  title={sidebarCollapsed ? item.label : undefined}
                  className={({ isActive }) =>
                    `block px-4 py-1.5 text-sm truncate ${sidebarCollapsed ? "text-center px-0" : ""} ${isActive ? "bg-[var(--accent-soft)] text-[var(--accent)] border-r-2 border-[var(--accent)]" : "text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--hover-overlay)]"}`
                  }
                >
                  {sidebarCollapsed ? item.label.slice(0, 2).toUpperCase() : item.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
      </aside>
      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-14 shrink-0 border-b border-[var(--border)] flex items-center justify-between px-6 bg-[var(--surface)]">
          <div className="flex items-center gap-4">
            <ViewSwitcher />
            {!isIntel && <div className="text-xs text-[var(--text-muted)]">Dubai Residential Market</div>}
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-[var(--text-muted)]">Period</span>
            <Select value={period} onChange={(v) => setPeriod(v as never)} options={PERIOD_OPTIONS} />
            <ThemeToggle />
          </div>
        </header>
        <main className={isIntel ? "flex-1 min-h-0 overflow-hidden p-6" : "flex-1 overflow-y-auto p-6"}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}

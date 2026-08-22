import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, type SearchSuggestItem } from "../lib/api";

const RECENT_KEY = "dre_recent_project_searches";
const MAX_RECENT = 6;

function loadRecent(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

function saveRecent(name: string) {
  try {
    const existing = loadRecent().filter((n) => n.toLowerCase() !== name.toLowerCase());
    localStorage.setItem(RECENT_KEY, JSON.stringify([name, ...existing].slice(0, MAX_RECENT)));
  } catch {
    // localStorage unavailable — recent searches are a convenience, not critical.
  }
}

function itemHref(item: SearchSuggestItem): string {
  return item.kind === "master" ? `/projects/${item.slug}` : `/projects/${item.master_slug}/buildings/${item.slug}`;
}

export function ProjectSearchBar() {
  const navigate = useNavigate();
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [recent, setRecent] = useState<string[]>(() => loadRecent());
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handle = setTimeout(() => setQuery(input.trim()), 250);
    return () => clearTimeout(handle);
  }, [input]);

  const { data, isFetching } = useQuery({
    queryKey: ["search-suggest", query],
    queryFn: () => api.searchSuggest(query, 10),
    enabled: query.length >= 2,
  });

  const items = query.length >= 2 ? (data?.items ?? []) : [];
  const showRecent = query.length < 2 && recent.length > 0;

  useEffect(() => {
    setActiveIndex(-1);
  }, [items.length, query]);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const goTo = (item: SearchSuggestItem) => {
    saveRecent(item.name);
    setRecent(loadRecent());
    setOpen(false);
    setInput("");
    setQuery("");
    navigate(itemHref(item));
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, items.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (activeIndex >= 0 && items[activeIndex]) {
        goTo(items[activeIndex]);
      } else if (items.length > 0) {
        goTo(items[0]);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div ref={containerRef} className="relative">
      <div className="relative">
        <span className="absolute left-4 top-1/2 -translate-y-1/2 text-[var(--text-muted)] text-lg">⌕</span>
        <input
          value={input}
          onChange={(e) => { setInput(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onKeyDown={handleKeyDown}
          placeholder="Search any project, building or development..."
          className="w-full bg-[var(--surface-2)] border border-[var(--border)] rounded-lg pl-11 pr-4 py-3.5 text-base text-[var(--text)] focus:outline-none focus:border-[var(--accent)] placeholder:text-[var(--text-muted)]"
        />
      </div>

      {open && (
        <div className="absolute z-20 mt-2 w-full bg-[var(--surface-2)] border border-[var(--border)] rounded-lg shadow-xl max-h-96 overflow-y-auto">
          {query.length >= 2 && isFetching && (
            <div className="px-4 py-3 text-sm text-[var(--text-muted)]">Searching...</div>
          )}

          {query.length >= 2 && !isFetching && items.length === 0 && (
            <div className="px-4 py-3 text-sm text-[var(--text-muted)]">No projects match "{query}".</div>
          )}

          {query.length >= 2 && !isFetching && items.map((item, i) => (
            <button
              key={`${item.kind}-${item.id}`}
              onClick={() => goTo(item)}
              onMouseEnter={() => setActiveIndex(i)}
              className={`block w-full text-left px-4 py-2.5 border-b border-[var(--border)]/40 last:border-b-0 ${i === activeIndex ? "bg-white/5" : ""}`}
            >
              <div className="text-sm text-[var(--text)]">{item.name}</div>
              <div className="text-xs text-[var(--text-muted)]">{item.subtitle}</div>
            </button>
          ))}

          {showRecent && (
            <>
              <div className="px-4 py-2 text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Recent Searches</div>
              {recent.map((name) => (
                <button
                  key={name}
                  onClick={() => { setInput(name); setQuery(name); }}
                  className="block w-full text-left px-4 py-2 text-sm text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-white/5"
                >
                  {name}
                </button>
              ))}
            </>
          )}

          {query.length < 2 && !showRecent && (
            <div className="px-4 py-3 text-xs text-[var(--text-muted)]">
              Try "Azizi Venice", "DAMAC Lagoons", "Sobha Hartland"...
            </div>
          )}
        </div>
      )}
    </div>
  );
}

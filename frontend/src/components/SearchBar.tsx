import { useEffect, useMemo, useRef, useState } from "react";
import { useAppStore } from "../state/appStore";
import { buildRoadIndex, dedupeHits, geocodePlaces, searchRoads, type SearchHit } from "../lib/search";
import { Icon } from "./Icons";

/** Friendly label for a hit's source. */
const kindLabel = (kind: string) =>
  kind === "street" ? "street" : kind === "poi" ? "place" : kind === "address" ? "address" : kind;

/**
 * Map omnibox (topbar center). Searches streets (local graph) + places (Mapbox
 * geocoding) and flies the camera to a pick. ⌘K / Ctrl+K focuses it.
 */
export function SearchBar() {
  const graph = useAppStore((s) => s.graph);
  const view = useAppStore((s) => s.view);
  const flyToHit = useAppStore((s) => s.flyToHit);
  const closeStreet = useAppStore((s) => s.closeStreet);
  const spanOnStreet = useAppStore((s) => s.spanOnStreet);

  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);

  const inputRef = useRef<HTMLInputElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  // Local road index — rebuilt only when the graph loads/changes.
  const roadIndex = useMemo(() => (graph ? buildRoadIndex(graph) : []), [graph]);

  // ⌘K / Ctrl+K to focus from anywhere.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Close on outside click.
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, []);

  // Debounced search: instant local roads, then merge in geocoded places.
  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setHits([]);
      return;
    }
    const local = searchRoads(roadIndex, q);
    setHits(dedupeHits(local));
    setActive(0);
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      geocodePlaces(q, ctrl.signal)
        .then((places) => setHits(dedupeHits([...local, ...places])))
        .catch(() => void 0); // network/abort — keep the local hits
    }, 180);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [query, roadIndex]);

  const dismiss = (label: string) => {
    setOpen(false);
    setQuery(label);
    inputRef.current?.blur();
  };

  const choose = async (h: SearchHit | undefined) => {
    if (!h) return;
    dismiss(h.label);
    // Shared camera logic (street frame+highlight / place retrieve+fly) lives in
    // the store so the copilot's focus reuses the exact same path.
    await flyToHit(h);
  };

  // Edit-mode actions on a street hit: seal the whole street, or arm the corridor tool.
  const editStreet = view === "edit";
  const doClose = (h: SearchHit) => {
    void closeStreet(h.label);
    dismiss(h.label);
  };
  const doSpan = (h: SearchHit) => {
    if (h.bbox) spanOnStreet(h.bbox);
    dismiss(h.label);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActive((i) => Math.min(i + 1, hits.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      void choose(hits[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
      inputRef.current?.blur();
    }
  };

  return (
    <div className="searchbar" ref={wrapRef}>
      <span className="sb-ico" aria-hidden>
        <Icon.search />
      </span>
      <input
        ref={inputRef}
        className="sb-input"
        value={query}
        placeholder="Search streets, places…"
        aria-label="Search the map"
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => query && setOpen(true)}
        onKeyDown={onKeyDown}
      />
      <kbd className="sb-kbd">⌘K</kbd>
      {open && hits.length > 0 && (
        <ul className="sb-results" role="listbox">
          {hits.map((h, i) => (
            <li
              key={h.id}
              role="option"
              aria-selected={i === active}
              className={`sb-row ${i === active ? "active" : ""}`}
              onMouseEnter={() => setActive(i)}
              onMouseDown={(e) => {
                e.preventDefault(); // keep focus; fire before blur
                void choose(h);
              }}
            >
              <span className="sb-row-ico">{h.kind === "street" ? <Icon.oneway /> : <Icon.pin />}</span>
              <span className="sb-row-label">{h.label}</span>
              {editStreet && h.kind === "street" ? (
                <span className="sb-row-actions">
                  <button
                    className="sb-act danger"
                    title={`Close all of ${h.label}`}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      doClose(h);
                    }}
                  >
                    Close
                  </button>
                  <button
                    className="sb-act"
                    title="Frame the street and pick a span to close"
                    onMouseDown={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      doSpan(h);
                    }}
                  >
                    Span
                  </button>
                </span>
              ) : (
                <span className="sb-row-kind">{kindLabel(h.kind)}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

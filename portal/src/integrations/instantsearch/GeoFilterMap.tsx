import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import MapGL, {
  Layer,
  Source,
  type LayerProps,
  type MapLayerMouseEvent,
  type MapRef,
  type ViewState,
} from "react-map-gl/maplibre";
import type { FeatureCollection } from "geojson";
import { useGeoSearch, useRefinementList } from "react-instantsearch";
import { cn } from "#/utils/cn";
import "maplibre-gl/dist/maplibre-gl.css";
import { useTheme } from "#/components/ThemeProvider";
import { m } from "#/paraglide/messages";

import { setWorkerUrl } from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import ArrowsPointingOutIcon from "@heroicons/react/24/solid/ArrowsPointingOutIcon";
import {
  MapIcon,
  PencilSquareIcon,
  ViewfinderCircleIcon,
  ArrowRightIcon,
  XMarkIcon,
} from "@heroicons/react/24/outline";
setWorkerUrl(workerUrl);

/**
 * Facet values look like "lat|lng|Place name" (see subject_locations_pt in the index).
 * That gives us accurate per-place counts WITH coordinates in a single facet query,
 * which respects the current query + all other filters. No hit paging needed.
 */

const STYLE_LIGHT = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";
const STYLE_DARK = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";

const EMPTY_FC: FeatureCollection = { type: "FeatureCollection", features: [] };

type Place = {
  value: string;
  name: string;
  lat: number;
  lng: number;
  count: number;
  selected: boolean;
};
type Box = { north: number; south: number; east: number; west: number };
type Hover = { x: number; y: number; name: string; count: number };
type PointerEv = Pick<MapLayerMouseEvent, "lngLat" | "point">;

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

function parsePlace(value: string, count: number, selected: boolean): Place | null {
  const [lat, lng, ...rest] = value.split("|");
  const la = Number(lat);
  const ln = Number(lng);
  if (!Number.isFinite(la) || !Number.isFinite(ln) || rest.length === 0) return null;
  return { value, name: rest.join("|"), lat: la, lng: ln, count, selected };
}

function boxFromPoints(a: { lng: number; lat: number }, b: { lng: number; lat: number }): Box {
  return {
    north: clamp(Math.max(a.lat, b.lat), -90, 90),
    south: clamp(Math.min(a.lat, b.lat), -90, 90),
    east: clamp(Math.max(a.lng, b.lng), -180, 180),
    west: clamp(Math.min(a.lng, b.lng), -180, 180),
  };
}

function boxToGeoJSON(b: Box | null): FeatureCollection {
  if (!b) return EMPTY_FC;
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: {},
        geometry: {
          type: "Polygon",
          coordinates: [
            [
              [b.west, b.south],
              [b.east, b.south],
              [b.east, b.north],
              [b.west, b.north],
              [b.west, b.south],
            ],
          ],
        },
      },
    ],
  };
}

/* ---------- static layer styles (module-level = stable references) ---------- */

const boxFillLayer: LayerProps = {
  id: "box-fill",
  type: "fill",
  paint: { "fill-color": "#22d3ee", "fill-opacity": 0.12 },
};
const boxLineLayer: LayerProps = {
  id: "box-line",
  type: "line",
  paint: { "line-color": "#22d3ee", "line-width": 2 },
};
const pointsLayer: LayerProps = {
  id: "points",
  type: "circle",
  paint: {
    "circle-radius": ["+", 3, ["*", 2, ["log10", ["+", 1, ["get", "count"]]]]],
    "circle-color": ["case", ["==", ["get", "selected"], 1], "#06b6d4", "#ffffff"],
    "circle-stroke-color": ["case", ["==", ["get", "selected"], 1], "#ffffff", "#06b6d4"],
    "circle-stroke-width": ["case", ["==", ["get", "selected"], 1], 2.5, 1.5],
    "circle-opacity": ["interpolate", ["linear"], ["zoom"], 2, 0.35, 6, 0.95],
    "circle-stroke-opacity": ["interpolate", ["linear"], ["zoom"], 2, 0.4, 6, 1],
  },
};

function ToolButton({
  active,
  onClick,
  children,
  title,
  className,
}: {
  active?: boolean;
  onClick: () => void;
  children: React.ReactNode;
  title?: string;
  className?: string;
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className={cn(
        "cursor-pointer rounded-md border px-2 py-1 text-xs font-medium shadow-sm backdrop-blur transition",
        active
          ? "border-cyan-500 bg-cyan-500 text-white"
          : "border-gray-200 bg-white/90 text-gray-700 hover:bg-white dark:border-gray-700 dark:bg-gray-900/90 dark:text-gray-200 dark:hover:bg-gray-800",
        className,
      )}
    >
      {children}
    </button>
  );
}

function SelectionButton({
  onClick,
  className,
  children,
}: {
  onClick: () => void;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1 rounded-full bg-cyan-50 text-cyan-700 dark:bg-cyan-950 dark:text-cyan-500 px-2 py-0.5 text-xs font-medium transition hover:bg-cyan-100 dark:hover:bg-cyan-800 cursor-pointer",
        className,
      )}
    >
      {children}
      <XMarkIcon className="text-cyan-400 h-3 w-3" />
    </button>
  );
}

export default function GeoFilterMap({
  attribute = "subject_locations_pt",
}: {
  attribute?: string;
}) {
  // Per-place counts + coordinates (disjunctive, so other places stay visible when you click one)
  const { items, refine } = useRefinementList({
    attribute,
    limit: 500,
    sortBy: ["count:desc"],
  });
  // Bounding-box refinement → insideBoundingBox search param → Typesense geo polygon filter
  const { currentRefinement, refine: refineBox, clearMapRefinement } = useGeoSearch();

  const theme = useTheme();
  const mapRef = useRef<MapRef>(null);
  const startRef = useRef<{ x: number; y: number; lng: number; lat: number } | null>(null);
  const fittedRef = useRef(false);

  const [loaded, setLoaded] = useState(false);
  const [view, setView] = useState<Partial<ViewState>>({ longitude: 10, latitude: 25, zoom: 0.8 });
  const [drawing, setDrawing] = useState(false);
  const [dragBox, setDragBox] = useState<Box | null>(null);
  const [hover, setHover] = useState<Hover | null>(null);

  const places = useMemo(
    () =>
      items
        .map((i) => parsePlace(i.value, i.count, i.isRefined))
        .filter((p): p is Place => p !== null),
    [items],
  );
  const selectedPlaces = places.filter((p) => p.selected);
  const maxCount = Math.max(1, ...places.map((p) => p.count));

  const geojson = useMemo<FeatureCollection>(
    () => ({
      type: "FeatureCollection",
      features: places.map((p) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [p.lng, p.lat] },
        properties: { value: p.value, name: p.name, count: p.count, selected: p.selected ? 1 : 0 },
      })),
    }),
    [places],
  );

  const applied = useMemo<Box | null>(
    () =>
      currentRefinement
        ? {
            north: currentRefinement.northEast.lat,
            east: currentRefinement.northEast.lng,
            south: currentRefinement.southWest.lat,
            west: currentRefinement.southWest.lng,
          }
        : null,
    [currentRefinement],
  );
  const shownBox = dragBox ?? applied;
  const boxGeo = useMemo(() => boxToGeoJSON(shownBox), [shownBox]);

  // Heat weight is log-scaled so one mega-city doesn't wash out everything else.
  const heatLayer = useMemo<LayerProps>(
    () => ({
      id: "heat",
      type: "heatmap",
      paint: {
        "heatmap-weight": [
          "interpolate",
          ["linear"],
          ["log10", ["+", 1, ["get", "count"]]],
          0,
          0,
          Math.log10(maxCount + 1),
          1,
        ],
        "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 0, 1, 9, 3],
        "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 0, 14, 9, 48],
        "heatmap-opacity": ["interpolate", ["linear"], ["zoom"], 6, 1, 10, 0.25],
        "heatmap-color": [
          "interpolate",
          ["linear"],
          ["heatmap-density"],
          0,
          "rgba(34,211,238,0)",
          0.2,
          "rgba(34,211,238,0.35)",
          0.45,
          "rgba(14,165,233,0.6)",
          0.7,
          "rgba(99,102,241,0.8)",
          1,
          "rgba(217,70,239,0.95)",
        ],
      },
    }),
    [maxCount],
  );

  /* ---------- camera ---------- */

  const fit = useCallback(
    (duration = 600) => {
      const map = mapRef.current;
      if (!map || places.length === 0) return;
      let w = 180,
        s = 90,
        e = -180,
        n = -90;
      for (const p of places) {
        w = Math.min(w, p.lng);
        e = Math.max(e, p.lng);
        s = Math.min(s, p.lat);
        n = Math.max(n, p.lat);
      }
      map.fitBounds(
        [
          [w, s],
          [e, n],
        ],
        { padding: 40, maxZoom: 4, duration },
      );
    },
    [places],
  );

  // Fit once, when the first data lands. After that the user owns the camera.
  useEffect(() => {
    if (loaded && !fittedRef.current && places.length > 0) {
      fit(0);
      fittedRef.current = true;
    }
  }, [loaded, places, fit]);

  /* ---------- box drawing ---------- */

  useEffect(() => {
    if (!drawing) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        startRef.current = null;
        setDragBox(null);
        setDrawing(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawing]);

  const startDraw = (e: PointerEv) => {
    if (!drawing) return;
    startRef.current = { x: e.point.x, y: e.point.y, lng: e.lngLat.lng, lat: e.lngLat.lat };
    setDragBox(boxFromPoints(e.lngLat, e.lngLat));
  };

  const moveDraw = (e: PointerEv) => {
    const start = startRef.current;
    if (start) setDragBox(boxFromPoints(start, e.lngLat));
  };

  const endDraw = (e: PointerEv) => {
    const start = startRef.current;
    if (!start) return;
    startRef.current = null;
    const moved = Math.abs(e.point.x - start.x) > 6 && Math.abs(e.point.y - start.y) > 6;
    if (moved) {
      const b = boxFromPoints(start, e.lngLat);
      refineBox({
        northEast: { lat: b.north, lng: b.east },
        southWest: { lat: b.south, lng: b.west },
      });
    }
    setDragBox(null);
    setDrawing(false);
  };

  const cancelDraw = () => {
    if (!startRef.current) return;
    startRef.current = null;
    setDragBox(null);
  };

  const searchView = () => {
    const b = mapRef.current?.getBounds();
    if (!b) return;
    refineBox({
      northEast: { lat: clamp(b.getNorth(), -90, 90), lng: clamp(b.getEast(), -180, 180) },
      southWest: { lat: clamp(b.getSouth(), -90, 90), lng: clamp(b.getWest(), -180, 180) },
    });
  };

  /* ---------- hover / click on places ---------- */

  const onMouseMove = (e: MapLayerMouseEvent) => {
    if (startRef.current) return moveDraw(e);
    const f = !drawing ? e.features?.[0] : undefined;
    if (!f) {
      if (hover) setHover(null);
      return;
    }
    const { name, count } = f.properties as { name: string; count: number };
    setHover({ x: e.point.x, y: e.point.y, name, count });
  };

  const onClick = (e: MapLayerMouseEvent) => {
    if (drawing) return;
    const value = e.features?.[0]?.properties?.value as string | undefined;
    if (value) refine(value);
  };

  if (places.length === 0 && !applied) return null;

  return (
    <div>
      <div className="relative h-56 overflow-hidden rounded-lg border border-gray-200 dark:border-gray-700">
        <MapGL
          key={theme.resolvedTheme === "dark" ? "dark" : "light"}
          ref={mapRef}
          {...view}
          onMove={(e) => setView(e.viewState)}
          onLoad={() => setLoaded(true)}
          mapStyle={theme.resolvedTheme === "dark" ? STYLE_DARK : STYLE_LIGHT}
          interactiveLayerIds={["points"]}
          cursor={drawing ? "crosshair" : hover ? "pointer" : "grab"}
          dragPan={!drawing}
          dragRotate={false}
          boxZoom={false}
          doubleClickZoom={!drawing}
          maxPitch={0}
          minZoom={0.5}
          renderWorldCopies={false}
          attributionControl={{ compact: true }}
          onMouseDown={(e) => {
            if (drawing) e.originalEvent.preventDefault();
            startDraw(e);
          }}
          onMouseMove={onMouseMove}
          onMouseUp={endDraw}
          onMouseOut={() => {
            cancelDraw();
            setHover(null);
          }}
          onTouchStart={startDraw}
          onTouchMove={moveDraw}
          onTouchEnd={endDraw}
          onClick={onClick}
          style={{
            width: "100%",
            height: "100%",
          }}
        >
          <Source id="heat-src" type="geojson" data={geojson}>
            <Layer {...heatLayer} />
          </Source>
          <Source id="box-src" type="geojson" data={boxGeo}>
            <Layer {...boxFillLayer} />
            <Layer {...boxLineLayer} />
          </Source>
          <Source id="pts-src" type="geojson" data={geojson}>
            <Layer {...pointsLayer} />
          </Source>
        </MapGL>

        <div className="absolute top-2 left-2 flex gap-1">
          <ToolButton
            active={drawing}
            onClick={() => setDrawing((d) => !d)}
            title={m.drawRectangle()}
            className="flex items-center gap-1"
          >
            <PencilSquareIcon className="h-3 w-3" /> {drawing ? m.drag() : m.draw()}
          </ToolButton>
          <ToolButton
            onClick={searchView}
            title={m.filterHint()}
            className="flex items-center gap-1"
          >
            <ViewfinderCircleIcon className="h-3 w-3" /> {m.thisView()}
          </ToolButton>
          <ToolButton onClick={() => fit()} title={m.zoomHint()}>
            <ArrowsPointingOutIcon className="h-3 w-3" />
          </ToolButton>
        </div>

        <div className="pointer-events-none absolute bottom-2 left-2 flex items-center gap-1.5 text-[10px] font-medium text-gray-500 dark:text-gray-400">
          <span>{m.fewer()}</span>
          <span className="h-1.5 w-14 rounded-full bg-linear-to-r from-cyan-300 via-indigo-500 to-fuchsia-500" />
          <span>{m.more()}</span>
        </div>

        {hover && (
          <div
            className="pointer-events-none absolute z-10 rounded-md bg-gray-900/90 px-2 py-1 text-xs text-white shadow-lg"
            style={{ left: hover.x + 12, top: hover.y + 12 }}
          >
            <div className="font-medium">{JSON.parse(hover?.name).label}</div>
            <div className="text-gray-300">{m.datasetCount({ count: hover.count })}</div>
          </div>
        )}
      </div>

      {(applied || selectedPlaces.length > 0) && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {applied && (
            <SelectionButton onClick={() => clearMapRefinement()}>
              <MapIcon className="h-3 w-3" /> {applied.north.toFixed(1)}°, {applied.west.toFixed(1)}
              ° <ArrowRightIcon className="h-3 w-3" /> {applied.south.toFixed(1)}
              °, {applied.east.toFixed(1)}°
            </SelectionButton>
          )}
          {selectedPlaces.map((p) => (
            <SelectionButton key={p.value} onClick={() => refine(p.value)}>
              {JSON.parse(p.name).label}
            </SelectionButton>
          ))}
        </div>
      )}

      <p className="mt-2 text-[11px] text-gray-400">{m.geoFilterHint()}</p>
    </div>
  );
}

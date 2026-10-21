import { lazy, Suspense, useEffect, useState } from "react";

// MapLibre is ~800KB: keep it out of the main bundle and off the server.
const GeoFilterMap = lazy(() => import("./GeoFilterMap"));

export function GeoFilter({ attribute = "subject_locations_pt" }: { attribute?: string }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const skeleton = <div className="h-56 animate-pulse rounded-lg bg-gray-100 dark:bg-gray-800" />;

  if (!mounted) return skeleton;

  return (
    <Suspense fallback={skeleton}>
      <GeoFilterMap attribute={attribute} />
    </Suspense>
  );
}

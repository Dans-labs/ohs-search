export function formatDate(value?: string | number | null) {
  if (value === undefined || value === null || value === "") return null;

  let date: Date;
  if (typeof value === "number" || /^\d+$/.test(value)) {
    const n = Number(value);
    // 10 digits or fewer = seconds, otherwise milliseconds
    date = new Date(n < 1e11 ? n * 1000 : n);
  } else {
    date = new Date(value); // ISO strings etc.
  }

  if (Number.isNaN(date.getTime())) return String(value);

  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(date);
}

export function formatBytes(bytes?: number) {
  if (!bytes || bytes === 0) return null;
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

const HAS_EXPLICIT_TIMEZONE = /(Z|[+-]\d{2}:\d{2})$/i

function normalizeApiDate(value: string): string {
  const trimmed = value.trim()
  if (!trimmed) return trimmed

  if (HAS_EXPLICIT_TIMEZONE.test(trimmed)) {
    return trimmed
  }

  if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) {
    return `${trimmed}T00:00:00Z`
  }

  return `${trimmed}Z`
}

export function parseApiDate(value: string): Date {
  return new Date(normalizeApiDate(value))
}

export function formatDateTimeLocal(
  value: string,
  options?: Intl.DateTimeFormatOptions,
): string {
  return parseApiDate(value).toLocaleString(undefined, options)
}

export function formatDateLocal(
  value: string,
  options?: Intl.DateTimeFormatOptions,
): string {
  return parseApiDate(value).toLocaleDateString(undefined, options)
}

export function getBrowserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "Local time"
}

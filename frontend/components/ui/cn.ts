/**
 * Minimal classNames joiner — no clsx/twMerge dep, no Tailwind class deduplication.
 * Falsy values (null, undefined, false) are skipped so conditional classes work.
 */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

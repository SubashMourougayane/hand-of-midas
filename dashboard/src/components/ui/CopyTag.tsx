import { useState } from "react";

// Click-to-copy inline tag. Renders `text` in mono; on click copies `value`
// (defaults to `text`) to the clipboard and flashes a "copied" tick. Swallows
// the click (stopPropagation) so it never triggers a parent row/card onClick.
export function CopyTag({
  text,
  value,
  className = "",
  title,
}: {
  text: string;
  value?: string;
  className?: string;
  title?: string;
}) {
  const [copied, setCopied] = useState(false);

  const onCopy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    const toCopy = value ?? text;
    try {
      await navigator.clipboard.writeText(toCopy);
    } catch {
      // Fallback for non-secure contexts / older browsers.
      const ta = document.createElement("textarea");
      ta.value = toCopy;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
      } catch {
        /* give up silently */
      }
      document.body.removeChild(ta);
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  };

  return (
    <button
      type="button"
      onClick={onCopy}
      title={title ?? `Copy ${text}`}
      className={`group/copy inline-flex items-center gap-1 font-mono hover:text-ink-primary transition-colors cursor-pointer max-md:min-h-9 ${className}`}
    >
      <span className="truncate">{text}</span>
      <span
        className={`text-ds-xs ${copied ? "text-bull" : "text-ink-dim opacity-0 group-hover/copy:opacity-100"} transition-opacity`}
        aria-hidden
      >
        {copied ? "✓" : "⧉"}
      </span>
    </button>
  );
}

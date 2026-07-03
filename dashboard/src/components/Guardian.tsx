import * as React from "react";

/**
 * Midas — the vault guardian. A fictional metallic-gold genie-sprite that lives
 * in a hidden compartment at the top of the login card and peeks out to react.
 *
 * Pure SVG + CSS (no deps). Expression + pose are props; LoginPage runs the
 * timeline (peek → look → react → drop) by swapping `expr` and toggling
 * `emerge`. All motion honours prefers-reduced-motion at the CSS layer.
 */
export type GuardianExpr =
  | "idle"
  | "curious"
  | "mischief" // wrong password — huge grin
  | "cool" // attempt 2 — sunglasses
  | "facepalm" // attempt 4
  | "suspicious" // attempt 5+
  | "proud"; // correct

export function Guardian({
  emerge = false,
  expr = "idle",
  wag = false,
  className = "",
}: {
  emerge?: boolean;
  expr?: GuardianExpr;
  wag?: boolean;
  className?: string;
}) {
  const grin = expr === "mischief" || expr === "cool" || expr === "proud";
  const frown = expr === "facepalm" || expr === "suspicious";
  const eyesWide = expr === "curious" || expr === "proud";
  const brows = frown;

  return (
    <div
      className={`guardian ${emerge ? "guardian-emerge" : "guardian-hidden"} ${className}`}
      aria-hidden
    >
      <div className="guardian-bob">
        <svg width="150" height="168" viewBox="0 0 150 168" fill="none">
          <defs>
            <radialGradient id="g-skin" cx="46%" cy="34%" r="72%">
              <stop offset="0%" stopColor="#fff6d8" />
              <stop offset="40%" stopColor="#f0cf6a" />
              <stop offset="78%" stopColor="#c9992b" />
              <stop offset="100%" stopColor="#8f6512" />
            </radialGradient>
            <linearGradient id="g-tail" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#f0cf6a" />
              <stop offset="100%" stopColor="rgba(201,153,43,0)" />
            </linearGradient>
            <radialGradient id="g-halo" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="rgba(232,198,90,0.55)" />
              <stop offset="100%" stopColor="rgba(232,198,90,0)" />
            </radialGradient>
            <linearGradient id="g-crown" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#fff3c4" />
              <stop offset="100%" stopColor="#d8a52a" />
            </linearGradient>
          </defs>

          {/* halo */}
          <circle cx="75" cy="78" r="66" fill="url(#g-halo)" className="guardian-aura" />

          {/* floating wisp tail (genie base) */}
          <path
            className="guardian-tail"
            d="M62 120 C58 138, 70 146, 66 158 C74 150, 80 158, 86 150 C84 140, 92 132, 88 120 Z"
            fill="url(#g-tail)"
          />

          {/* ---- arms ---- */}
          <g className={wag ? "guardian-arm-wag" : "guardian-arm-l"}>
            <path d="M44 96 C30 98, 24 108, 30 116 C34 110, 40 106, 48 106 Z" fill="url(#g-skin)" />
            <circle cx="30" cy="114" r="6" fill="url(#g-skin)" />
          </g>
          <g className="guardian-arm-r">
            <path d="M106 96 C120 98, 126 108, 120 116 C116 110, 110 106, 102 106 Z" fill="url(#g-skin)" />
            <circle cx="120" cy="114" r="6" fill="url(#g-skin)" />
          </g>

          {/* ---- body ---- */}
          <path
            d="M75 66 C96 66, 104 84, 100 104 C97 118, 86 124, 75 124 C64 124, 53 118, 50 104 C46 84, 54 66, 75 66 Z"
            fill="url(#g-skin)"
            stroke="rgba(255,246,216,0.55)"
            strokeWidth="1.2"
          />
          {/* chest gem */}
          <path d="M75 92 L81 100 L75 110 L69 100 Z" fill="#fff3c4" opacity="0.9" />

          {/* ---- head ---- */}
          <circle cx="75" cy="48" r="30" fill="url(#g-skin)" stroke="rgba(255,246,216,0.6)" strokeWidth="1.2" />
          {/* cheek sheen */}
          <ellipse cx="64" cy="40" rx="12" ry="8" fill="rgba(255,255,255,0.3)" />

          {/* crown */}
          <path
            className="guardian-crown"
            d="M55 24 L61 12 L68 22 L75 8 L82 22 L89 12 L95 24 Z"
            fill="url(#g-crown)"
            stroke="rgba(143,101,18,0.5)"
            strokeWidth="0.8"
          />
          <circle cx="75" cy="8" r="3" fill="#fff6d8" className="guardian-gem" />

          {/* pointy ears */}
          <path d="M46 46 L38 40 L47 54 Z" fill="url(#g-skin)" />
          <path d="M104 46 L112 40 L103 54 Z" fill="url(#g-skin)" />

          {/* brows (only when frowning) */}
          {brows && (
            <>
              <path d="M58 34 L72 40" stroke="#5a3d0a" strokeWidth="2.6" strokeLinecap="round" />
              <path d="M92 34 L78 40" stroke="#5a3d0a" strokeWidth="2.6" strokeLinecap="round" />
            </>
          )}

          {/* eyes */}
          <g className="guardian-eyes">
            <ellipse cx="64" cy={eyesWide ? 46 : 48} rx="8" ry={eyesWide ? 11 : 9} fill="#2a1c06" />
            <ellipse cx="86" cy={eyesWide ? 46 : 48} rx="8" ry={eyesWide ? 11 : 9} fill="#2a1c06" />
            <circle cx="67" cy="44" r="2.8" fill="#fff" />
            <circle cx="89" cy="44" r="2.8" fill="#fff" />
          </g>

          {/* sunglasses (attempt 2 — cool) */}
          {expr === "cool" && (
            <g className="guardian-shades">
              <rect x="53" y="42" width="20" height="13" rx="5" fill="#0c0a05" />
              <rect x="77" y="42" width="20" height="13" rx="5" fill="#0c0a05" />
              <rect x="73" y="46" width="4" height="3" fill="#0c0a05" />
              <rect x="55" y="44" width="7" height="3" rx="1.5" fill="rgba(232,198,90,0.75)" />
            </g>
          )}

          {/* mouth */}
          {grin ? (
            <path d="M62 60 Q75 76, 88 60 Q75 68, 62 60 Z" fill="#3a1d0a" className="guardian-mouth" />
          ) : frown ? (
            <path d="M64 66 Q75 58, 86 66" stroke="#3a1d0a" strokeWidth="3" strokeLinecap="round" fill="none" />
          ) : (
            <path d="M67 62 Q75 68, 83 62" stroke="#3a1d0a" strokeWidth="3" strokeLinecap="round" fill="none" />
          )}
          {/* little fang for mischief */}
          {expr === "mischief" && <path d="M70 62 L73 68 L76 62 Z" fill="#fff6d8" />}

          {/* facepalm hand over face */}
          {expr === "facepalm" && (
            <g className="guardian-palm">
              <ellipse cx="75" cy="48" rx="20" ry="16" fill="url(#g-skin)" opacity="0.96" />
              <path d="M62 40 L62 56 M69 38 L69 58 M76 38 L76 58 M83 40 L83 56" stroke="rgba(143,101,18,0.4)" strokeWidth="1.4" strokeLinecap="round" />
            </g>
          )}
        </svg>
      </div>
    </div>
  );
}

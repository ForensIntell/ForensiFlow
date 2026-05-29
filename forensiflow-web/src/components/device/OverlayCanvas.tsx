export function OverlayCanvas() {
  return (
    <svg
      className="absolute inset-0 w-full h-full pointer-events-none"
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
    >
      <defs>
        <filter id="glow">
          <feGaussianBlur stdDeviation="0.3" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* XML node: chat item 1 */}
      <rect x="8" y="18" width="84" height="9" rx="1.5"
        fill="rgba(56,189,248,0.06)" stroke="#38bdf8" strokeWidth="0.3"
        vectorEffect="non-scaling-stroke" />
      <text x="9" y="17" fill="#38bdf8" fontSize="2.2" fontFamily="monospace" opacity="0.8">XML</text>

      {/* XML node: chat item 2 */}
      <rect x="8" y="28.5" width="84" height="9" rx="1.5"
        fill="rgba(56,189,248,0.06)" stroke="#38bdf8" strokeWidth="0.3"
        vectorEffect="non-scaling-stroke" />

      {/* XML node: chat item 3 */}
      <rect x="8" y="39" width="84" height="9" rx="1.5"
        fill="rgba(56,189,248,0.06)" stroke="#38bdf8" strokeWidth="0.3"
        vectorEffect="non-scaling-stroke" />

      {/* OCR text area */}
      <rect x="12" y="52" width="50" height="5" rx="1"
        fill="rgba(52,211,153,0.06)" stroke="#34d399" strokeWidth="0.25"
        strokeDasharray="1 0.5"
        vectorEffect="non-scaling-stroke" />
      <text x="13" y="51" fill="#34d399" fontSize="2" fontFamily="monospace" opacity="0.7">OCR</text>

      {/* Target element: the matched contact */}
      <rect x="8" y="28.5" width="84" height="9" rx="1.5"
        fill="rgba(37,99,235,0.08)" stroke="#2563eb" strokeWidth="0.5"
        vectorEffect="non-scaling-stroke" filter="url(#glow)" />
      <text x="9" y="27.5" fill="#2563eb" fontSize="2.2" fontWeight="600" fontFamily="monospace">Target</text>

      {/* Subtle scan line effect */}
      <line x1="0" y1="50" x2="100" y2="50" stroke="rgba(37,99,235,0.1)" strokeWidth="0.15"
        vectorEffect="non-scaling-stroke">
        <animate attributeName="y1" values="0;100;0" dur="8s" repeatCount="indefinite" />
        <animate attributeName="y2" values="0;100;0" dur="8s" repeatCount="indefinite" />
      </line>
    </svg>
  );
}

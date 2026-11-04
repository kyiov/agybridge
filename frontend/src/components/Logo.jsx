export default function Logo({ size = 28, className = "" }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`shrink-0 transition-transform duration-200 hover:scale-105 ${className}`}
    >
      <defs>
        <linearGradient id="agyLeftWing" x1="5.5" y1="25.5" x2="16" y2="5.5" gradientUnits="userSpaceOnUse">
          <stop stopColor="#7c3aed" />
          <stop offset="1" stopColor="#a855f7" />
        </linearGradient>
        <linearGradient id="agyRightWing" x1="16" y1="5.5" x2="26.5" y2="25.5" gradientUnits="userSpaceOnUse">
          <stop stopColor="#a855f7" />
          <stop offset="1" stopColor="#38bdf8" />
        </linearGradient>
        <linearGradient id="agyCoreBeam" x1="11" y1="19.5" x2="21" y2="19.5" gradientUnits="userSpaceOnUse">
          <stop stopColor="#c084fc" />
          <stop offset="1" stopColor="#38bdf8" />
        </linearGradient>
        <filter id="agyGlow" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="1" result="blur" />
          <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
      </defs>

      {/* Sayap Kiri Minimalis */}
      <path
        d="M16 5.5L5.5 25.5H10.2L16 14.5Z"
        fill="url(#agyLeftWing)"
      />

      {/* Sayap Kanan Minimalis dengan Gradien Biru Muda / Cyan */}
      <path
        d="M16 5.5L16 14.5L21.8 25.5H26.5Z"
        fill="url(#agyRightWing)"
      />

      {/* Palang Melayang (Anti-Gravity Floating Bar) */}
      <rect
        x="11"
        y="18.2"
        width="10"
        height="2.6"
        rx="1.3"
        fill="url(#agyCoreBeam)"
        filter="url(#agyGlow)"
      />

      {/* Inti Cahaya Gateway */}
      <circle cx="16" cy="10.8" r="1.5" fill="#ffffff" />
    </svg>
  );
}

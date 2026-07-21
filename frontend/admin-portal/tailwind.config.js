/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: "#6366f1",
          50: "#eef2ff",
          100: "#e0e7ff",
          200: "#c7d2fe",
          300: "#a5b4fc",
          400: "#818cf8",
          500: "#6366f1",
          600: "#4f46e5",
          700: "#4338ca",
          800: "#3730a3",
          900: "#312e81",
        },
        secondary: "#64748b",
        surface: "rgba(255, 255, 255, 0.65)",
        "surface-subtle": "rgba(255, 255, 255, 0.4)",
        "surface-dark": "rgba(15, 23, 42, 0.55)",
        border: "rgba(148, 163, 184, 0.28)",
        success: "#10b981",
        warning: "#f59e0b",
        danger: "#ef4444",
        info: "#0ea5e9",
      },
      backgroundImage: {
        "mesh-gradient":
          "radial-gradient(at 0% 0%, rgba(99, 102, 241, 0.25) 0px, transparent 50%), radial-gradient(at 100% 0%, rgba(56, 189, 248, 0.22) 0px, transparent 50%), radial-gradient(at 100% 100%, rgba(168, 85, 247, 0.2) 0px, transparent 50%), radial-gradient(at 0% 100%, rgba(16, 185, 129, 0.18) 0px, transparent 50%)",
        "glass-sheen":
          "linear-gradient(135deg, rgba(255,255,255,0.5) 0%, rgba(255,255,255,0.08) 100%)",
      },
      boxShadow: {
        glass: "0 8px 32px 0 rgba(31, 38, 135, 0.12)",
        "glass-lg": "0 20px 60px -10px rgba(31, 38, 135, 0.25)",
        glow: "0 0 24px 0 rgba(99, 102, 241, 0.35)",
        "glow-sm": "0 0 12px 0 rgba(99, 102, 241, 0.25)",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(12px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        scaleIn: {
          "0%": { opacity: "0", transform: "scale(0.95)" },
          "100%": { opacity: "1", transform: "scale(1)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-400px 0" },
          "100%": { backgroundPosition: "400px 0" },
        },
        floatSlow: {
          "0%, 100%": { transform: "translate(0, 0) scale(1)" },
          "50%": { transform: "translate(20px, -30px) scale(1.05)" },
        },
        glowPulse: {
          "0%, 100%": { opacity: "0.6" },
          "50%": { opacity: "1" },
        },
      },
      animation: {
        "fade-in": "fadeIn 0.4s ease-out both",
        "slide-up": "slideUp 0.45s cubic-bezier(0.16, 1, 0.3, 1) both",
        "scale-in": "scaleIn 0.3s ease-out both",
        shimmer: "shimmer 1.6s infinite linear",
        "float-slow": "floatSlow 10s ease-in-out infinite",
        "float-slower": "floatSlow 16s ease-in-out infinite",
        "glow-pulse": "glowPulse 2.4s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

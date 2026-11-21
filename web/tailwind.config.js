/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        parchment: {
          50: "#fffdf9",
          100: "#faf4e8",
          200: "#f2e7d3",
          300: "#e4d2b4",
          400: "#cfb489",
        },
        alice: {
          50: "#eff6ff",
          100: "#dbeafe",
          200: "#bfdbfe",
          500: "#2b5b84",
          600: "#1e4568",
          700: "#16344f",
        },
        queen: {
          50: "#fff1f2",
          100: "#ffe4e6",
          500: "#c81e3a",
          600: "#a5152e",
          700: "#881326",
        },
        cheshire: {
          50: "#f5f3ff",
          100: "#ede9fe",
          500: "#6d28d9",
          600: "#5b21b6",
        },
        hatter: {
          50: "#ecfdf5",
          100: "#d1fae5",
          500: "#047857",
          600: "#065f46",
        },
        gold: {
          100: "#fef3c7",
          400: "#d97706",
          500: "#b45309",
          600: "#92400e",
        },
      },
      fontFamily: {
        serif: [
          "Fraunces",
          "Iowan Old Style",
          "Palatino Linotype",
          "Georgia",
          "serif",
        ],
        sans: [
          "Plus Jakarta Sans",
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          "sans-serif",
        ],
        mono: [
          "JetBrains Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Monaco",
          "Consolas",
          "monospace",
        ],
      },
      boxShadow: {
        storybook: "0 10px 30px -12px rgba(64, 42, 18, 0.14), 0 2px 6px -1px rgba(64, 42, 18, 0.06)",
        bubble: "0 6px 20px -6px rgba(35, 31, 26, 0.12)",
      },
    },
  },
  plugins: [],
};

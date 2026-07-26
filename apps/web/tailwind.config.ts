import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        paper: "#f7f1e8",
        ink: "#1c1612",
        muted: "#6b5e52",
        line: "#d9cbb8",
        copper: "#b86b3c",
        "copper-deep": "#8f4e2a",
        sage: "#4f6f5a",
        wash: "#e5d6c4",
        atelier: "#f0e8dc",
      },
      fontFamily: {
        display: ["var(--font-display)", "Fraunces", "Georgia", "serif"],
        body: ["var(--font-body)", "Source Sans 3", "sans-serif"],
      },
    },
  },
  plugins: [],
};
export default config;


import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#10233f",
        slate: "#5f7392",
        mist: "#edf3fb",
        accent: "#0f766e",
        panel: "#ffffff",
      },
      boxShadow: {
        panel: "0 18px 50px rgba(16, 35, 63, 0.08)",
      },
    },
  },
  plugins: [],
} satisfies Config;

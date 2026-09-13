/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        sap: {
          blue: '#0a6ed1',
          dark: '#1d232a',
          sidebar: '#111827',
          gold: '#df6e0c',
          border: '#374151',
        },
      },
    },
  },
  plugins: [],
}

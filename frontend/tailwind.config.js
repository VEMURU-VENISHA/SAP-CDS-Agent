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
          blue: '#0A6ED1',
          action: '#1677FF',
          navy: '#0F2747',
          text: '#172B4D',
          subtext: '#5F7187',
          bg: '#F4F8FC',
          card: '#FFFFFF',
          border: '#D9E4F0',
          green: '#00A878',
          greenBg: '#E8F8F3',
        },
      },
      fontFamily: {
        sans: ['72', 'Inter', 'Segoe UI', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
      },
    },
  },
  plugins: [],
}


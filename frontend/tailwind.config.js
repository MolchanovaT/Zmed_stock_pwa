/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,jsx,ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50:  '#eef4fb',
          100: '#d0e3f4',
          500: '#2c5f8a',
          600: '#1e4a73',
          700: '#163959',
        },
      },
    },
  },
  plugins: [],
}

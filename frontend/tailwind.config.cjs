/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      spacing: {
        112: '28rem',
        128: '32rem',
      },
      colors: {
        'eerie-black': '#212121',
        jet: '#343541',
        'gray-alpha': 'rgba(0,0,0, .1)',
      },
    },
  },
  plugins: [],
};

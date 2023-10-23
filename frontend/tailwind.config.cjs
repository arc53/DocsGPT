/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      spacing: {
        112: '28rem',
        128: '32rem',
      },
      colors: {
        'eerie-black': '#212121',
        'custom-black': '#000000', // Change the color 'black-1000' to pure black
        jet: '#343541',
        'gray-alpha': 'rgba(0,0,0, .1)',
        'gray-1000': '#F6F6F6', // Change the color 'gray-1000'
        'gray-2000': 'rgba(0, 0, 0, 0.5)',
        'gray-3000': 'rgba(243, 243, 243, 1)',
        'custom-gray': '#888888', // Add a custom gray color
        'red-1000': 'rgb(254, 202, 202)',
        'red-2000': '#F44336',
        'red-3000': '#621B16',
        'blue-1000': '#7D54D1',
        'blue-2000': '#002B49',
        'blue-3000': '#4B02E2',
        'purple-30': '#7D54D1',
        'blue-4000': 'rgba(0, 125, 255, 0.36)',
        'custom-blue': '#0088CC', // Add a custom blue color
        'blue-5000': 'rgba(0, 125, 255)',
      },
    },
  },
  plugins: [],
};

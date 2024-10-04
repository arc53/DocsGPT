/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{html,js}"],
  theme: {
    extend: {},
  },
  plugins: [],
}


// Frontend/src/App.js

import React, { useState } from 'react';
import './darkmode.css'; // Ensure you import the dark mode CSS here

function App() {
    const [darkMode, setDarkMode] = useState(false);

    const toggleDarkMode = () => {
        setDarkMode(!darkMode);
        document.body.classList.toggle('dark-mode', !darkMode);
    };

    return (
        <div className={darkMode ? 'dark-mode' : ''}>
            <button onClick={toggleDarkMode}>
                {darkMode ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
            </button>
            {/* Rest of your app components */}
        </div>
    );
}

export default App;

import { useState } from "react";
//import "./App.css";
import {DocsGPTWidget} from "./components/DocsGPTWidget";

function App() {
  const [count, setCount] = useState(0);

  return (
    <div className="App">
      <DocsGPTWidget />
    </div>
  );
}

export default App;

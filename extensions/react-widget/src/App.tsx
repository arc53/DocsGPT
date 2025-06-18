import React from "react"
import {DocsGPTWidget} from "./components/DocsGPTWidget"
import {SearchBar} from "./components/SearchBar"
export const App = () => {
  return (
    <div>
      <SearchBar/>
      <DocsGPTWidget/>
    </div>
  )
}
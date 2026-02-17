import { DocsGPTWidget } from "docsgpt-react";

export default function MyApp({ Component, pageProps }) {
  return (
    <>
      <Component {...pageProps} />
        <DocsGPTWidget showSources={true} apiKey="5d8270cb-735f-484e-9dc9-5b407f24e652" theme="dark" size="medium" />
    </>
  )
}

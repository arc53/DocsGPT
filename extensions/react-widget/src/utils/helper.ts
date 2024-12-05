import MarkdownIt from "markdown-it";
import DOMPurify from "dompurify";
export const getOS = () => {
  const platform = window.navigator.platform;
  const userAgent = window.navigator.userAgent || window.navigator.vendor;

  if (/Mac/i.test(platform)) {
    return 'mac';
  }

  if (/Win/i.test(platform)) {
    return 'win';
  }

  if (/Linux/i.test(platform) && !/Android/i.test(userAgent)) {
    return 'linux';
  }

  if (/Android/i.test(userAgent)) {
    return 'android';
  }

  if (/iPhone|iPad|iPod/i.test(userAgent)) {
    return 'ios';
  }

  return 'other';
};

export const preprocessSearchResultsToHTML = (text: string, keyword: string) => {
  const md = new MarkdownIt();
  const htmlString = md.render(text);
  const parser = new DOMParser();
  const doc = parser.parseFromString(htmlString, "text/html");

  const filteredResults = document.createElement("div")
  recursiveFilter(doc.body, keyword, filteredResults)
  console.log(filteredResults)

  return DOMPurify.sanitize(filteredResults)

}

const recursiveFilter = (element: Node, keyword: string, parent: Node | null) => {
  const content = element.textContent?.toLowerCase() ?? null;
  const childNodes = element.childNodes
  childNodes.forEach((child) => {
    if (recursiveFilter(child, keyword, element))
      parent?.appendChild(highlightFilteredContent(child, keyword))
  })
  if (content && content.includes(keyword.toLowerCase())) {
    return true
  }
  return false
}

const highlightFilteredContent = (element: Node, keyword: string) => {
  if (!element.textContent || !keyword.trim()) return element;

  const regex = new RegExp(`(${keyword})`, 'gi');
  const splitted = element.textContent.split(regex);
  console.log(splitted);

  // Create a new HTML string with the keyword wrapped in a <span>
  const highlightedHTML = splitted
    .map((part) =>
      regex.test(part)
        ? `<span style="color: yellow;">${part}</span>`
        : part
    )
    .join("");
  if (element instanceof HTMLElement) {
    element.innerHTML = highlightedHTML;
  }
  return element
};
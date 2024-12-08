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

  // Container for processed HTML
  const filteredResults = document.createElement("div");
  filteredResults.innerHTML = htmlString;

  if (!processNode(filteredResults, keyword)) return null;

  return filteredResults.innerHTML.trim() ? filteredResults.outerHTML : null;
};



// Recursive function to process nodes
const processNode = (node: Node, keyword: string): boolean => {

  const keywordRegex = new RegExp(`(${keyword})`, "gi");
  if (node.nodeType === Node.TEXT_NODE) {
    const textContent = node.textContent || "";

    if (textContent.toLowerCase().includes(keyword.toLowerCase())) {
      const highlightedHTML = textContent.replace(
        keywordRegex,
        `<mark>$1</mark>`
      );
      const tempContainer = document.createElement("div");
      tempContainer.innerHTML = highlightedHTML;

      // Replace the text node with highlighted content
      while (tempContainer.firstChild) {
        node.parentNode?.insertBefore(tempContainer.firstChild, node);
      }
      node.parentNode?.removeChild(node);

      return true;
    }

    return false;
  } else if (node.nodeType === Node.ELEMENT_NODE) {

    const children = Array.from(node.childNodes);
    let hasKeyword = false;

    children.forEach((child) => {
      if (!processNode(child, keyword)) {
        node.removeChild(child);
      } else {
        hasKeyword = true;
      }
    });

    return hasKeyword;
  }

  return false;
};
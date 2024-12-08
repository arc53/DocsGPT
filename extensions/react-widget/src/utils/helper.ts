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
  const filteredResults = document.createElement("div")
  filteredResults.innerHTML = htmlString;
  console.log(filteredResults);
  
  //iterator for nodes not including the keyword
  const nodeIterator = document.createNodeIterator(
    filteredResults,
    NodeFilter.SHOW_ELEMENT,
    {
      acceptNode(node) {
        return !node.textContent?.toLowerCase().includes(keyword.toLowerCase())
          ? NodeFilter.FILTER_ACCEPT
          : NodeFilter.FILTER_REJECT;
      },
    },
  );

  //remove each node from the DOM not containg the 
  let currentNode;
  while ((currentNode = nodeIterator.nextNode())) {
    currentNode.parentElement?.removeChild(currentNode);
  }
  if (!filteredResults.innerHTML.trim())
    return null;
  return filteredResults.outerHTML
}

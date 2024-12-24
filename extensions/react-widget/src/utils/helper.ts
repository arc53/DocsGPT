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

interface MarkdownElement {
  type: 'heading' | 'paragraph' | 'code' | 'list' | 'other';
  content: string;
  level?: number;
}

interface ParsedElement {
  content: string;
  tag: string;
}

export const processMarkdownString = (markdown: string): ParsedElement[] => {
  const result: ParsedElement[] = [];
  const lines = markdown.trim().split('\n');
  
  let isInCodeBlock = false;
  let currentCodeBlock = '';

  for (let i = 0; i < lines.length; i++) {
    const trimmedLine = lines[i].trim();
    if (!trimmedLine) continue;

    if (trimmedLine.startsWith('```')) {
      if (isInCodeBlock) {
        if (currentCodeBlock.trim()) {
          result.push({
            content: currentCodeBlock.trim(),
            tag: 'code'
          });
        }
        currentCodeBlock = '';
        isInCodeBlock = false;
      } else {
        isInCodeBlock = true;
      }
      continue;
    }

    if (isInCodeBlock) {
      currentCodeBlock += trimmedLine + '\n';
      continue;
    }

    const headingMatch = trimmedLine.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      result.push({
        content: headingMatch[2],
        tag: 'heading'
      });
      continue;
    }

    const bulletMatch = trimmedLine.match(/^[-*]\s+(.+)$/);
    if (bulletMatch) {
      result.push({
        content: bulletMatch[1],
        tag: 'bulletList'
      });
      continue;
    }

    const numberedMatch = trimmedLine.match(/^\d+\.\s+(.+)$/);
    if (numberedMatch) {
      result.push({
        content: numberedMatch[1],
        tag: 'numberedList'
      });
      continue;
    }

    result.push({
      content: trimmedLine,
      tag: 'text'
    });
  }

  if (isInCodeBlock && currentCodeBlock.trim()) {
    result.push({
      content: currentCodeBlock.trim(),
      tag: 'code'
    });
  }

  return result;
};

export const preprocessSearchResultsToHTML = (text: string, keyword: string): MarkdownElement[] | null => {
  const md = new MarkdownIt();
  const tokens = md.parse(text, {});
  const results: MarkdownElement[] = [];
  
  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i];
    
    if (token.type.endsWith('_close') || !token.content) continue;

    const content = token.content.toLowerCase();
    const keywordLower = keyword.trim().toLowerCase();
    
    if (!content.includes(keywordLower)) continue;

    switch (token.type) {
      case 'heading_open':
        const level = parseInt(token.tag.charAt(1));
        const headingContent = tokens[i + 1].content;
        results.push({
          type: 'heading',
          content: headingContent,
          level
        });
        break;

      case 'paragraph_open':
        const paragraphContent = tokens[i + 1].content;
        results.push({
          type: 'paragraph',
          content: paragraphContent
        });
        break;

      case 'fence':
      case 'code_block':
        results.push({
          type: 'code',
          content: token.content
        });
        break;

      case 'bullet_list_open':
      case 'ordered_list_open':
        let listItems = [];
        i++;
        while (i < tokens.length && !tokens[i].type.includes('list_close')) {
          if (tokens[i].type === 'list_item_open') {
            i++;
            if (tokens[i].content) {
              listItems.push(tokens[i].content);
            }
          }
          i++;
        }
        if (listItems.length > 0) {
          results.push({
            type: 'list',
            content: listItems.join('\n')
          });
        }
        break;

      default:
        if (token.content) {
          results.push({
            type: 'other',
            content: token.content
          });
        }
        break;
    }
  }

  return results.length > 0 ? results : null;
};

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

const markdownString = `
# Title
This is a paragraph.

## Subtitle
- Bullet item 1
* Bullet item 2
1. Numbered item 1
2. Numbered item 2

\`\`\`javascript
const hello = "world";
console.log(hello);
// This is a multi-line
// code block
\`\`\`

Regular text after code block
`;

const parsed = processMarkdownString(markdownString);
console.log(parsed);

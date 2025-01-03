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

interface ParsedElement {
  content: string;
  tag: string;
}

export const processMarkdownString = (markdown: string, keyword?: string): ParsedElement[] => {
  const lines = markdown.trim().split('\n');
  const keywordLower = keyword?.toLowerCase();

  const escapeRegExp = (str: string) => str.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&');
  const escapedKeyword = keyword ? escapeRegExp(keyword) : '';
  const keywordRegex = keyword ? new RegExp(`(${escapedKeyword})`, 'gi') : null;

  let isInCodeBlock = false;
  let codeBlockContent: string[] = [];
  let matchingLines: ParsedElement[] = [];
  let firstLine: ParsedElement | null = null;

  for (let i = 0; i < lines.length; i++) {
    const trimmedLine = lines[i].trim();
    if (!trimmedLine) continue;

    if (trimmedLine.startsWith('```')) {
      if (!isInCodeBlock) {
        isInCodeBlock = true;
        codeBlockContent = [];
      } else {
        isInCodeBlock = false;
        const codeContent = codeBlockContent.join('\n');
        const parsedElement: ParsedElement = {
          content: codeContent,
          tag: 'code'
        };

        if (!firstLine) {
          firstLine = parsedElement;
        }

        if (keywordLower && codeContent.toLowerCase().includes(keywordLower)) {
          parsedElement.content = parsedElement.content.replace(keywordRegex!, '<span class="highlight">$1</span>');
          matchingLines.push(parsedElement);
        }
      }
      continue;
    }

    if (isInCodeBlock) {
      codeBlockContent.push(trimmedLine);
      continue;
    }

    let parsedElement: ParsedElement | null = null;

    const headingMatch = trimmedLine.match(/^(#{1,6})\s+(.+)$/);
    const bulletMatch = trimmedLine.match(/^[-*]\s+(.+)$/);
    const numberedMatch = trimmedLine.match(/^\d+\.\s+(.+)$/);
    const blockquoteMatch = trimmedLine.match(/^>+\s*(.+)$/);

    let content = trimmedLine;

    if (headingMatch) {
      content = headingMatch[2];
      parsedElement = {
        content: content,
        tag: 'heading'
      };
    } else if (bulletMatch) {
      content = bulletMatch[1];
      parsedElement = {
        content: content,
        tag: 'bulletList'
      };
    } else if (numberedMatch) {
      content = numberedMatch[1];
      parsedElement = {
        content: content,
        tag: 'numberedList'
      };
    } else if (blockquoteMatch) {
      content = blockquoteMatch[1];
      parsedElement = {
        content: content,
        tag: 'blockquote'
      };
    } else {
      parsedElement = {
        content: content,
        tag: 'text'
      };
    }

    if (!firstLine) {
      firstLine = parsedElement;
    }

    if (keywordLower && parsedElement.content.toLowerCase().includes(keywordLower)) {
      parsedElement.content = parsedElement.content.replace(keywordRegex!, '<span class="highlight">$1</span>');
      matchingLines.push(parsedElement);
    }
  }

  if (isInCodeBlock && codeBlockContent.length > 0) {
    const codeContent = codeBlockContent.join('\n');
    const parsedElement: ParsedElement = {
      content: codeContent,
      tag: 'code'
    };

    if (!firstLine) {
      firstLine = parsedElement;
    }

    if (keywordLower && codeContent.toLowerCase().includes(keywordLower)) {
      parsedElement.content = parsedElement.content.replace(keywordRegex!, '<span class="highlight">$1</span>');
      matchingLines.push(parsedElement);
    }
  }

  if (keywordLower && matchingLines.length > 0) {
    return matchingLines;
  }

  return firstLine ? [firstLine] : [];
};

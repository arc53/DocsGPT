const github = 'https://github.com/arc53/DocsGPT';

/**
 * The site footer under every page: licence, the DocsGPT site, GitHub and the blog.
 *
 * @returns {import('react').JSX.Element} The footer.
 */
export function SiteFooter() {
  return (
    <footer className="mt-8 border-t pt-6 text-sm text-fd-muted-foreground">
      <span>MIT {new Date().getFullYear()} © </span>
      <a href="https://www.docsgpt.cloud/" target="_blank" rel="noreferrer" className="hover:text-fd-foreground">
        DocsGPT
      </a>
      {' | '}
      <a href={github} target="_blank" rel="noreferrer" className="hover:text-fd-foreground">
        GitHub
      </a>
      {' | '}
      <a href="https://www.docsgpt.cloud/blog" target="_blank" rel="noreferrer" className="hover:text-fd-foreground">
        Blog
      </a>
    </footer>
  );
}

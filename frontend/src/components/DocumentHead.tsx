import React from 'react';

interface DocumentHeadProps {
  title?: string;
  description?: string;
  keywords?: string;
  ogTitle?: string;
  ogDescription?: string;
  ogImage?: string;
  twitterCard?: string;
  twitterTitle?: string;
  twitterDescription?: string;
  children?: React.ReactNode;
}

export function DocumentHead({
  title,
  description,
  keywords,
  ogTitle,
  ogDescription,
  ogImage,
  twitterCard,
  twitterTitle,
  twitterDescription,
  children,
}: DocumentHeadProps) {
  return (
    <>
      {title && <title>{title}</title>}
      {description && <meta name="description" content={description} />}
      {keywords && <meta name="keywords" content={keywords} />}

      {/* Open Graph */}
      {ogTitle && <meta property="og:title" content={ogTitle} />}
      {ogDescription && (
        <meta property="og:description" content={ogDescription} />
      )}
      {ogImage && <meta property="og:image" content={ogImage} />}

      {/* Twitter */}
      {twitterCard && <meta name="twitter:card" content={twitterCard} />}
      {twitterTitle && <meta name="twitter:title" content={twitterTitle} />}
      {twitterDescription && (
        <meta name="twitter:description" content={twitterDescription} />
      )}

      {/* Additional elements */}
      {children}
    </>
  );
}

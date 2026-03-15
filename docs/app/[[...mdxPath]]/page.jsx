import { generateStaticParamsFor, importPage } from 'nextra/pages';

import { useMDXComponents } from '../../mdx-components';

export const generateStaticParams = generateStaticParamsFor('mdxPath');

export async function generateMetadata(props) {
  const params = await props.params;
  const { metadata } = await importPage(params?.mdxPath);
  return metadata;
}

const Wrapper = useMDXComponents().wrapper;

export default async function Page(props) {
  const params = await props.params;
  const result = await importPage(params?.mdxPath);
  const { default: MDXContent, metadata, sourceCode, toc } = result;

  return (
    <Wrapper metadata={metadata} sourceCode={sourceCode} toc={toc}>
      <MDXContent {...props} params={params} />
    </Wrapper>
  );
}

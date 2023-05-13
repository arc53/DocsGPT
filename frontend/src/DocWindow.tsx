export default function DocWindow(props: { html: string }) {
  if (props.html === '') {
    return <div>Here is the section to show the document the answer from.</div>;
  }

  return (
    <>
      <div dangerouslySetInnerHTML={{ __html: props.html }} />
    </>
  );
}

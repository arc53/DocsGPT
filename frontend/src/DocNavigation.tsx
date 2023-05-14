export default function DocNavigation(props: { index: string }) {
  if (props.index === '') {
    return <div>Here is the section to show the doc navigation.</div>;
  }

  return (
    <>
      <div dangerouslySetInnerHTML={{ __html: props.index }} />
    </>
  );
}

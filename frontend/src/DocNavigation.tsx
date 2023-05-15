import NavigationTree from './NavigationTree';
export default function DocNavigation(props: { index: string }) {
  if (props.index === '') {
    return <div></div>;
  }

  let parseData = JSON.parse(props.index);
  // console.log('parsed');
  // console.log(parseData);
  parseData.forEach(function1);
  function function1(currentValue: string, index: string) {
    console.log('Index is: ' + index + ' Value is: ' + currentValue);
  }

  return (
    <>
      <NavigationTree data={parseData}></NavigationTree>
    </>
  );
}

export const handleClick = (event: MouseEvent) => {
  event.preventDefault();
  const anchor = event.target as HTMLAnchorElement;
  const url = new URL(anchor.href.replace(/%5C/g, '/'));

  console.log('Path:', url.pathname);
  let pathname = url.pathname;
  if (pathname.startsWith('/')) {
    pathname = pathname.slice(1);
  }
  fetch('http://localhost:5001/api/get_docs', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      user: 'local',
      path: pathname,
    }),
  })
    .then((response) => {
      return response.text();
    })
    .then((data) => console.log(data))
    .catch((error) => {
      console.log('Error: ', error);
    });
};

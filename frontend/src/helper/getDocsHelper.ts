export const handleClick = (
  event: MouseEvent,
  onLinkClicked: {
    (data: string): void;
    (data: string): void;
    (arg0: string): void;
  },
) => {
  event.preventDefault();
  const anchor = event.target as HTMLAnchorElement;
  const url = new URL(anchor.href.replace(/%5C/g, '/'));
  console.log('Path:', url.pathname);
  let path = url.pathname;
  if (path.startsWith('/')) {
    path = path.slice(1);
  }
  fetch('http://localhost:5001/api/get_docs', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      user: 'local',
      path: path,
    }),
  })
    .then(async (response) => {
      return response.text();
    })
    .then((data) => {
      console.log(data);
      onLinkClicked(data);
    })
    .catch((error) => {
      console.log('Error: ', error);
    });
};

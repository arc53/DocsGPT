export let globalSetFilepath = 'a';

export const handleClick = (event: MouseEvent) => {
  event.preventDefault();
  const anchor = event.target as HTMLAnchorElement;
  const url = new URL(anchor.href.replace(/%5C/g, '/'));
  console.log('Path:', url.pathname);
  globalSetFilepath = url.pathname;
  if (globalSetFilepath.startsWith('/')) {
    globalSetFilepath = globalSetFilepath.slice(1);
  }
  fetch('http://localhost:5001/api/get_docs', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      user: 'local',
      path: globalSetFilepath,
    }),
  })
    .then(async (response) => {
      return response.text();
    })
    .then((data) => console.log('data:' + data))
    .catch((error) => {
      console.log('Error: ', error);
    });
};

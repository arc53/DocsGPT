import jsonServer from 'json-server';
import routes from './mocks/routes.json' assert { type: "json" };


const server = jsonServer.create();
const router = jsonServer.router('./src/mocks/db.json');
const middlewares = jsonServer.defaults();

server.use(middlewares);
server.use(jsonServer.rewriter(routes));


server.use(router);

server.listen(7091, () => {
  console.log('JSON Server is running')
});
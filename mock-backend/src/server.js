import jsonServer from "json-server";
import routes from "./mocks/routes.json" assert { type: "json" };

const server = jsonServer.create();
const router = jsonServer.router("./src/mocks/db.json");
const middlewares = jsonServer.defaults();

server.use(middlewares);

server.use((req, res, next) => {
  if (req.method === "POST") {
    if (req.url.includes("/delete_conversation")) {
      req.method = "DELETE";
    }
  }
  next();
});

server.use(jsonServer.rewriter(routes));

router.render = (req, res) => {
  if (req.url === "/feedback") {
    res.status(200).jsonp({ status: "ok" });
  }
};

server.use(router);

server.listen(7091, () => {
  console.log("JSON Server is running");
});

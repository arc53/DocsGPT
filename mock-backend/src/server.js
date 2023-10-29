import jsonServer from "json-server";
import routes from "./mocks/routes.json" assert { type: "json" };
import { v4 as uuid } from "uuid";

const server = jsonServer.create();
const router = jsonServer.router("./src/mocks/db.json");
const middlewares = jsonServer.defaults();

const localStorage = [];

server.use(middlewares);

server.use(jsonServer.rewriter(routes));

server.use((req, res, next) => {
  if (req.method === "POST") {
    if (req.url.includes("/delete_conversation")) {
      req.method = "DELETE";
    } else if (req.url === "/upload") {
      const taskId = uuid();
      localStorage.push(taskId);
    }
  }
  next();
});

router.render = (req, res) => {
  if (req.url === "/feedback") {
    res.status(200).jsonp({ status: "ok" });
  } else if (req.url === "/upload") {
    res.status(200).jsonp({
      status: "ok",
      task_id: localStorage[localStorage.length - 1],
    });
  } else if (req.url.includes("/task_status")) {
    const taskId = req.query["task_id"];
    const taskIdExists = localStorage.includes(taskId);
    if (taskIdExists) {
      res.status(200).jsonp({
        result: {
          directory: "temp",
          filename: "install.rst",
          formats: [".rst", ".md", ".pdf"],
          name_job: "somename",
          user: "local",
        },
        status: "SUCCESS",
      });
    } else {
      res.status(404).jsonp({});
    }
  } else if (req.url === "/stream") {
    res.status(200).jsonp({
      data: "The answer is 42",
      sources: [
        "https://en.wikipedia.org/wiki/42_(number)",
        "https://en.wikipedia.org/wiki/42_(number)",
      ],
      conversation_id: "1234",
    });
  } else {
    res.status(res.statusCode).jsonp(res.locals.data);
  }
};

server.use(router);

server.listen(7091, () => {
  console.log("JSON Server is running");
});

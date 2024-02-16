import jsonServer from "json-server";
import routes from "./mocks/routes.json" assert { type: "json" };
import { v4 as uuid } from "uuid";
import cors from 'cors'
const server = jsonServer.create();
const router = jsonServer.router("./src/mocks/db.json");
const middlewares = jsonServer.defaults();

const localStorage = [];

server.use(middlewares);
server.use(cors({ origin: ['*'] }))
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
  } else if (req.url === "/stream" && req.method === "POST") {
    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive'
    });
    const message = ('Hi, How are you today?').split(' ');
    let index = 0;
    const interval = setInterval(() => {
      if (index < message.length) {
        res.write(`data: {"answer": "${message[index++]} "}\n`);
      } else {
        res.write(`data: {"type": "id", "id": "65cbc39d11f077b9eeb06d26"}\n`)
        res.write(`data: {"type": "end"}\n`)
        clearInterval(interval); // Stop the interval once the message is fully streamed
        res.end(); // End the response
      }
    }, 500); // Send a word every 1 second
  }
  else if (req.url === '/search' && req.method === 'POST') {
    res.status(200).json(
      [
        {
          "text": "\n\n/api/answer\nIt's a POST request that sends a JSON in body with 4 values. It will receive an answer for a user provided question.\n",
          "title": "API-docs.md"
        },
        {
          "text": "\n\nOur Standards\n\nExamples of behavior that contribute to a positive environment for our\ncommunity include:\n* Demonstrating empathy and kindness towards other people\n",
          "title": "How-to-use-different-LLM.md"
        }
      ]
    )
  }
  else if (req.url === '/get_prompts' && req.method === 'GET') {
    res.status(200).json([
      {
        "id": "default",
        "name": "default",
        "type": "public"
      },
      {
        "id": "creative",
        "name": "creative",
        "type": "public"
      },
      {
        "id": "strict",
        "name": "strict",
        "type": "public"
      }
    ]);
  }
  else if (req.url.startsWith('/get_single_prompt') && req.method==='GET') {
    const id = req.query.id;
    console.log('hre');
    if (id === 'creative')
      res.status(200).json({
        "content": "You are a DocsGPT, friendly and helpful AI assistant by Arc53 that provides help with documents. You give thorough answers with code examples if possible."
      })
    else if (id === 'strict') {
      res.status(200).json({
        "content": "You are an AI Assistant, DocsGPT, adept at offering document assistance. \nYour expertise lies in providing answer on top of provided context."
      })
    }
    else {
      res.status(200).json({
        "content": "You are a helpful AI assistant, DocsGPT, specializing in document assistance, designed to offer detailed and informative responses."
      })
    }
  }
  else {
    res.status(res.statusCode).jsonp(res.locals.data);
  }
};

server.use(router);

server.listen(7091, () => {
  console.log("JSON Server is running");
});

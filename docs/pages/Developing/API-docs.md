App currently has two main api endpoints:

### /api/answer 
Its a POST request that sends a JSON in body with 4 values. Here is a JavaScript fetch example
It will recieve an answer for a user provided question

```
// answer (POST http://127.0.0.1:5000/api/answer)
fetch("http://127.0.0.1:5000/api/answer", {
      "method": "POST",
      "headers": {
            "Content-Type": "application/json; charset=utf-8"
      },
      "body": JSON.stringify({"question":"Hi","history":null,"api_key":"OPENAI_API_KEY","embeddings_key":"OPENAI_API_KEY",
      "active_docs": "javascript/.project/ES2015/openai_text-embedding-ada-002/"})
})
.then((res) => res.text())
.then(console.log.bind(console))
```

In response you will get a json document like this one:

```
{
  "answer": " Hi there! How can I help you?\n",
  "query": "Hi",
  "result": " Hi there! How can I help you?\nSOURCES:"
}
```

### /api/docs_check
It will make sure documentation is loaded on a server (just run it everytime user is switching between libraries (documentations)
Its a POST request that sends a JSON in body with 1 value. Here is a JavaScript fetch example

```
// answer (POST http://127.0.0.1:5000/api/docs_check)
fetch("http://127.0.0.1:5000/api/docs_check", {
      "method": "POST",
      "headers": {
            "Content-Type": "application/json; charset=utf-8"
      },
      "body": JSON.stringify({"docs":"javascript/.project/ES2015/openai_text-embedding-ada-002/"})
})
.then((res) => res.text())
.then(console.log.bind(console))
```

In response you will get a json document like this one:
```
{
  "status": "exists"
}
```


### /api/combine
Provides json that tells UI which vectors are available and where they are located with a simple get request

Respsonse will include:
date, description, docLink, fullName, language, location (local or docshub), model, name, version

Example of json in Docshub and local:
<img width="295" alt="image" src="https://user-images.githubusercontent.com/15183589/224714085-f09f51a4-7a9a-4efb-bd39-798029bb4273.png">


### /api/upload
Uploads file that needs to be trained, response is json with task id, which can be used to check on tasks progress
HTML example:

```
<form action="/api/upload" method="post" enctype="multipart/form-data" class="mt-2">
                <input type="file" name="file" class="py-4" id="file-upload">
                <input type="text" name="user" value="local" hidden>
                <input type="text" name="name" placeholder="Name:">


              <button type="submit" class="py-2 px-4 text-white bg-blue-500 rounded-md hover:bg-blue-600 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500">
                Upload
              </button>
            </form>
```

Response:
```
{
  "status": "ok",
  "task_id": "b2684988-9047-428b-bd47-08518679103c"
}

```

### /api/task_status
Gets task status (task_id) from /api/upload
```
// Task status (Get http://127.0.0.1:5000/api/task_status)
fetch("http://localhost:5001/api/task_status?task_id=b2d2a0f4-387c-44fd-a443-e4fe2e7454d1", {
      "method": "GET",
      "headers": {
            "Content-Type": "application/json; charset=utf-8"
      },
})
.then((res) => res.text())
.then(console.log.bind(console))
```

Responses:
There are two types of repsonses:
1. while task it still running, where "current" will show progress from 0 - 100
```
{
  "result": {
    "current": 1
  },
  "status": "PROGRESS"
}
```

2. When task is completed
```
{
  "result": {
    "directory": "temp",
    "filename": "install.rst",
    "formats": [
      ".rst",
      ".md",
      ".pdf"
    ],
    "name_job": "somename",
    "user": "local"
  },
  "status": "SUCCESS"
}
```

### /api/delete_old
deletes old vecotstores
```
// Task status (GET http://127.0.0.1:5000/api/docs_check)
fetch("http://localhost:5001/api/task_status?task_id=b2d2a0f4-387c-44fd-a443-e4fe2e7454d1", {
      "method": "GET",
      "headers": {
            "Content-Type": "application/json; charset=utf-8"
      },
})
.then((res) => res.text())
.then(console.log.bind(console))
```
response:

```
{"status": 'ok'}
```

# API Endpoints Documentation

*Currently, the application provides the following main API endpoints:*


### 1. /api/answer 
**Description:**

This endpoint is used to request answers to user-provided questions.

**Request:**

**Method**: `POST`

**Headers**: Content-Type should be set to `application/json; charset=utf-8`

**Request Body**: JSON object with the following fields:
* `question` — The user's question.
* `history`  —  (Optional) Previous conversation history.
* `api_key`— Your API key.
* `embeddings_key`  —  Your embeddings key.
* `active_docs` — The location of active documentation.

Here is a JavaScript Fetch Request example:
```js
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

**Response**

In response, you will get a JSON document containing the `answer`, `query` and `result`:
```json
{
  "answer": "Hi there! How can I help you?\n",
  "query": "Hi",
  "result": "Hi there! How can I help you?\nSOURCES:"
}
```

### 2. /api/docs_check

**Description:**

This endpoint will make sure documentation is loaded on the server (just run it every time user is switching between libraries (documentations)).

**Request:**

**Headers**: Content-Type should be set to `application/json; charset=utf-8`

**Request Body**: JSON object with the field:
* `docs` — The location of the documentation:
```js
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

**Response:**

In response, you will get a JSON document like this one indicating whether the documentation exists or not:
```json
{
  "status": "exists"
}
```


### 3. /api/combine
**Description:**

This endpoint provides information about available vectors and their locations with a simple GET request.

**Request:**

**Method**: `GET`

**Response:**

Response will include:
* `date`
* `description`
* `docLink`
* `fullName`
* `language`
* `location` (local or docshub)
* `model`
* `name`
* `version`

Example of JSON in Docshub and local:

<img width="295" alt="image" src="https://user-images.githubusercontent.com/15183589/224714085-f09f51a4-7a9a-4efb-bd39-798029bb4273.png">

### 4. /api/upload
**Description:**

This endpoint is used to upload a file that needs to be trained, response is JSON with task ID, which can be used to check on task's progress.

**Request:**

**Method**: `POST`

**Request Body**: A multipart/form-data form with file upload and additional fields, including `user` and `name`.

HTML example:

```html
<form action="/api/upload" method="post" enctype="multipart/form-data" class="mt-2">
    <input type="file" name="file" class="py-4" id="file-upload">
    <input type="text" name="user" value="local" hidden>
    <input type="text" name="name" placeholder="Name:">
    
    <button type="submit" class="py-2 px-4 text-white bg-purple-30 rounded-md hover:bg-purple-30 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-purple-30">
        Upload
    </button>
</form>
```

**Response:**

JSON response with a status and a task ID that can be used to check the task's progress.


### 5. /api/task_status
**Description:**

This endpoint is used to get the status of a task (`task_id`) from `/api/upload`

**Request:**

**Method**: `GET`

**Query Parameter**: `task_id` (task ID to check)

**Sample JavaScript Fetch Request:**
```js
// Task status (Get http://127.0.0.1:5000/api/task_status)
fetch("http://localhost:5001/api/task_status?task_id=YOUR_TASK_ID", {
      "method": "GET",
      "headers": {
            "Content-Type": "application/json; charset=utf-8"
      },
})
.then((res) => res.text())
.then(console.log.bind(console))
```

**Response:**

There are two types of responses:

1. While the task is still running, the 'current' value will show progress from 0 to 100.
   ```json
   {
     "result": {
       "current": 1
     },
     "status": "PROGRESS"
   }
   ```

2. When task is completed:
   ```json
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

### 6. /api/delete_old
**Description:**

This endpoint is used to delete old Vector Stores.

**Request:**

**Method**: `GET`

```js
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
**Response:**

JSON response indicating the status of the operation:

```json
{ "status": "ok" }
```

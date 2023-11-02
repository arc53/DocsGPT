## How to train on other documentation

This AI can utilize any documentation, but it requires preparation for similarity search. Follow these steps to get your documentation ready:

**Step 1: Prepare Your Documentation**
![video-example-of-how-to-do-it](https://d3dg1063dc54p9.cloudfront.net/videos/how-to-vectorise.gif)

Start by going to `/scripts/` folder.

If you open this file, you will see that it uses RST files from the folder to create a `index.faiss` and `index.pkl`. 

It currently uses OPENAI to create the vector store, so make sure your documentation is not too large. Using Pandas cost me around $3-$4.

You can typically find documentation on GitHub in the `docs/` folder for most open-source projects.

### 1. Find documentation in .rst/.md format and create a folder with it in your scripts directory.
- Name it `inputs/`.
- Put all your .rst/.md files in there.  
- The search is recursive, so you don't need to flatten them.

If there are no .rst/.md files, convert whatever you find to a .txt file and feed it. (Don't forget to change the extension in the script).

### Step 2: Configure Your OpenAI API Key
1. Create a .env file in the scripts/ folder.
  - Add your OpenAI API key inside: OPENAI_API_KEY=<your-api-key>.

### Step 3: Run the Ingestion Script

`python ingest.py ingest`

It will provide you with the estimated cost.

### Step 4: Move `index.faiss` and `index.pkl` generated in `scripts/output` to `application/` folder. 


### Step 5: Run the Web App
Once you run it, it will use new context relevant to your documentation.Make sure you select default in the dropdown in the UI.

## Customization 
You can learn more about options while running ingest.py by running:
  - Make sure you select 'default' from the dropdown in the UI.

## Customization
You can learn more about options while running ingest.py by executing:
`python ingest.py --help`
|              Options             |                                                                                                                                |
|:--------------------------------:|:------------------------------------------------------------------------------------------------------------------------------:|
|            **ingest**            | Runs 'ingest' function, converting documentation to Faiss plus Index format                                                  |
| --dir TEXT                       | List of paths to directory for index creation. E.g. --dir inputs --dir inputs2 [default: inputs]                               |
| --file TEXT                      | File paths to use (Optional; overrides directory) E.g. --files inputs/1.md --files inputs/2.md                                 |
| --recursive / --no-recursive     | Whether to recursively search in subdirectories [default: recursive]                                                           |
| --limit INTEGER                  | Maximum number of files to read                                                                                                |
| --formats TEXT                   | List of required extensions (list with .) Currently supported: .rst, .md, .pdf, .docx, .csv, .epub, .html [default: .rst, .md] |
| --exclude / --no-exclude         | Whether to exclude hidden files (dotfiles) [default: exclude]                                                                  |
| -y, --yes                        | Whether to skip price confirmation                                                                                             |
| --sample / --no-sample           | Whether to output sample of the first 5 split documents. [default: no-sample]                                                  |
| --token-check / --no-token-check | Whether to group small documents and split large. Improves semantics. [default: token-check]                                   |
| --min_tokens INTEGER             | Minimum number of tokens to not group. [default: 150]                                                                          |
| --max_tokens INTEGER             | Maximum number of tokens to not split. [default: 2000]                                                                         |
|                                  |                                                                                                                                |
|            **convert**           | Creates documentation in .md format from source code                                                                           |
| --dir TEXT                       | Path to a directory with source code. E.g. --dir inputs [default: inputs]                                                      |
| --formats TEXT                   | Source code language from which to create documentation. Supports py, js and java.  E.g. --formats py [default: py]            |

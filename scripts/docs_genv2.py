from pathlib import Path
from langchain.text_splitter import CharacterTextSplitter
import faiss
from langchain.vectorstores import FAISS
from langchain.embeddings import OpenAIEmbeddings
from langchain.llms import OpenAI
from langchain.prompts import PromptTemplate
import pickle
import dotenv
import tiktoken
import sys
from argparse import ArgumentParser
import ast

dotenv.load_dotenv()


ps = list(Path("inputs").glob("**/*.py"))
data = []
sources = []
for p in ps:
    with open(p) as f:
        data.append(f.read())
    sources.append(p)





def get_all_functions(source_code):
    tree = ast.parse(source_code)
    functions = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            functions[node.name] = ast.unparse(node)

    return functions

def get_all_functions_names(node):
    functions = []
    for child in node.body:
        if isinstance(child, ast.FunctionDef):
            functions.append(child.name)
    return functions



def get_classes(source_code):
    tree = ast.parse(source_code)
    classes = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes[node.name] = get_all_functions_names(node)
    return classes

def get_functions_in_class(source_code, class_name):
    tree = ast.parse(source_code)
    functions = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            if node.name == class_name:
                for function in node.body:
                    if isinstance(function, ast.FunctionDef):
                        functions.append(function.name)
    return functions


functions_dict = {}
classes_dict = {}
c1 = 0
for code in data:
    functions = get_all_functions(ast.parse(code))
    source = str(sources[c1])
    functions_dict[source] = functions
    classes = get_classes(code)
    classes_dict[source] = classes
    c1 += 1



if not Path("outputs").exists():
    Path("outputs").mkdir()

c1 = len(functions_dict)
c2 = 0
functions_dict = {}
for source, functions in functions_dict.items():
    c2 += 1
    print(f"Processing file {c2}/{c1}")
    f1 = len(functions)
    f2 = 0
    source_w = source.replace("inputs/", "")
    source_w = source_w.replace(".py", ".md")
    # this is how we check subfolders
    if "/" in source_w:
        subfolders = source_w.split("/")
        subfolders = subfolders[:-1]
        subfolders = "/".join(subfolders)
        if not Path(f"outputs/{subfolders}").exists():
            Path(f"outputs/{subfolders}").mkdir(parents=True)

    for name, function in functions.items():
        f2 += 1
        print(f"Processing function {f2}/{f1}")
        prompt = PromptTemplate(
            input_variables=["code"],
            template="Code: \n{code}, \nDocumentation: ",
        )
        llm = OpenAI(temperature=0)
        response = llm(prompt.format(code=function))

        if not Path(f"outputs/{source_w}").exists():
            with open(f"outputs/{source_w}", "w") as f:
                f.write(f"# Function name: {name} \n\nFunction: \n```\n{function}\n```, \nDocumentation: \n{response}")
        else:
            with open(f"outputs/{source_w}", "a") as f:
                f.write(f"\n\n# Function name: {name} \n\nFunction: \n```\n{function}\n```, \nDocumentation: \n{response}")



c1 = len(classes_dict)
c2 = 0

for source, classes in classes_dict.items():
    c2 += 1
    print(f"Processing file {c2}/{c1}")
    f1 = len(classes)
    f2 = 0
    source_w = source.replace("inputs/", "")
    source_w = source_w.replace(".py", ".md")

    if "/" in source_w:
        subfolders = source_w.split("/")
        subfolders = subfolders[:-1]
        subfolders = "/".join(subfolders)
        if not Path(f"outputs/{subfolders}").exists():
            Path(f"outputs/{subfolders}").mkdir(parents=True)

    for name, function_names in classes.items():
        print(f"Processing Class {f2}/{f1}")
        f2 += 1
        prompt = PromptTemplate(
            input_variables=["class_name", "functions_names"],
            template="Class name: {class_name} \nFunctions: {functions_names}, \nDocumentation: ",
        )
        llm = OpenAI(temperature=0)
        response = llm(prompt.format(class_name=name, functions_names=function_names))

        if not Path(f"outputs/{source_w}").exists():
            with open(f"outputs/{source_w}", "w") as f:
                f.write(f"# Class name: {name} \n\nFunctions: \n{function_names}, \nDocumentation: \n{response}")
        else:
            with open(f"outputs/{source_w}", "a") as f:
                f.write(f"\n\n# Class name: {name} \n\nFunctions: \n{function_names}, \nDocumentation: \n{response}")







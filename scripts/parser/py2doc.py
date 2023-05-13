import ast
import os
from pathlib import Path

import tiktoken
from langchain.llms import OpenAI
from langchain.prompts import PromptTemplate


def find_files(directory):
    files_list = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                files_list.append(os.path.join(root, file))
    return files_list


def extract_functions(file_path):
    with open(file_path, 'r') as file:
        source_code = file.read()
        functions = {}
        tree = ast.parse(source_code)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                func_name = node.name
                func_def = ast.get_source_segment(source_code, node)
                functions[func_name] = func_def
    return functions


def extract_classes(file_path):
    with open(file_path, 'r') as file:
        source_code = file.read()
        classes = {}
        tree = ast.parse(source_code)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_name = node.name
                function_names = []
                for subnode in ast.walk(node):
                    if isinstance(subnode, ast.FunctionDef):
                        function_names.append(subnode.name)
                classes[class_name] = ", ".join(function_names)
    return classes


def extract_functions_and_classes(directory):
    files = find_files(directory)
    functions_dict = {}
    classes_dict = {}
    for file in files:
        functions = extract_functions(file)
        if functions:
            functions_dict[file] = functions
        classes = extract_classes(file)
        if classes:
            classes_dict[file] = classes
    return functions_dict, classes_dict


def parse_functions(functions_dict, formats, dir):
    c1 = len(functions_dict)
    for i, (source, functions) in enumerate(functions_dict.items(), start=1):
        print(f"Processing file {i}/{c1}")
        source_w = source.replace(dir + "/", "").replace("." + formats, ".md")
        subfolders = "/".join(source_w.split("/")[:-1])
        Path(f"outputs/{subfolders}").mkdir(parents=True, exist_ok=True)
        for j, (name, function) in enumerate(functions.items(), start=1):
            print(f"Processing function {j}/{len(functions)}")
            prompt = PromptTemplate(
                input_variables=["code"],
                template="Code: \n{code}, \nDocumentation: ",
            )
            llm = OpenAI(temperature=0)
            response = llm(prompt.format(code=function))
            mode = "a" if Path(f"outputs/{source_w}").exists() else "w"
            with open(f"outputs/{source_w}", mode) as f:
                f.write(
                    f"\n\n# Function name: {name} \n\nFunction: \n```\n{function}\n```, \nDocumentation: \n{response}")


def parse_classes(classes_dict, formats, dir):
    c1 = len(classes_dict)
    for i, (source, classes) in enumerate(classes_dict.items()):
        print(f"Processing file {i + 1}/{c1}")
        source_w = source.replace(dir + "/", "").replace("." + formats, ".md")
        subfolders = "/".join(source_w.split("/")[:-1])
        Path(f"outputs/{subfolders}").mkdir(parents=True, exist_ok=True)
        for name, function_names in classes.items():
            print(f"Processing Class {i + 1}/{c1}")
            prompt = PromptTemplate(
                input_variables=["class_name", "functions_names"],
                template="Class name: {class_name} \nFunctions: {functions_names}, \nDocumentation: ",
            )
            llm = OpenAI(temperature=0)
            response = llm(prompt.format(class_name=name, functions_names=function_names))

            with open(f"outputs/{source_w}", "a" if Path(f"outputs/{source_w}").exists() else "w") as f:
                f.write(f"\n\n# Class name: {name} \n\nFunctions: \n{function_names}, \nDocumentation: \n{response}")


def transform_to_docs(functions_dict, classes_dict, formats, dir):
    docs_content = ''.join([str(key) + str(value) for key, value in functions_dict.items()])
    docs_content += ''.join([str(key) + str(value) for key, value in classes_dict.items()])

    num_tokens = len(tiktoken.get_encoding("cl100k_base").encode(docs_content))
    total_price = ((num_tokens / 1000) * 0.02)

    print(f"Number of Tokens = {num_tokens:,d}")
    print(f"Approx Cost = ${total_price:,.2f}")

    user_input = input("Price Okay? (Y/N)\n").lower()
    if user_input == "y" or user_input == "":
        if not Path("outputs").exists():
            Path("outputs").mkdir()
        parse_functions(functions_dict, formats, dir)
        parse_classes(classes_dict, formats, dir)
        print("All done!")
    else:
        print("The API was not called. No money was spent.")

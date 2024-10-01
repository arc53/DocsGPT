import ast
import json
from pathlib import Path

import dotenv
from langchain_community.llms import OpenAI
from langchain.prompts import PromptTemplate

dotenv.load_dotenv()

ps = list(Path("inputs").glob("**/*.py"))
data = []
sources = []

# read the data
for p in ps:
    with open(p) as f:
        data.append(f.read())
    sources.append(p)


# get the functions in a class
def get_functions_in_class(node):
    functions = []
    functions_code = []
    for child in node.body:
        if isinstance(child, ast.FunctionDef):
            functions.append(child.name)
            functions_code.append(ast.unparse(child))

    return functions, functions_code


# get the classes and functions
def get_classes_and_functions(source_code):
    tree = ast.parse(source_code)
    classes = {}

    # iterate through the tree to get the classes and functions
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            class_name = node.name
            function_name, function = get_functions_in_class(node)
            # join function name and function code
            functions = dict(zip(function_name, function))
            classes[class_name] = functions
    return classes


# get the structure of the code
structure_dict = {}
class_count_1 = 0

# iterate through the data
for code in data:
    classes = get_classes_and_functions(ast.parse(code))
    source = str(sources[class_count_1])
    structure_dict[source] = classes
    class_count_1 += 1

# save the structure dict as json
with open('structure_dict.json', 'w') as f:
    json.dump(structure_dict, f)

# create a folder if it does not exist
if not Path("outputs").exists():
    Path("outputs").mkdir()

class_count_1 = len(structure_dict)
class_count_2 = 0

# iterate through the structure dict
for source, classes in structure_dict.items():
    class_count_2 += 1
    print(f"Processing file {class_count_2}/{class_count_1}")

    f1 = len(classes)
    f2 = 0

    # iterate through the classes for each source code
    for class_name, functions in classes.items():
        f2 += 1
        print(f"Processing class {f2}/{f1}")
        source_w = source.replace("inputs/", "")
        source_w = source_w.replace(".py", ".txt")

        # write class name to the file
        if not Path(f"outputs/{source_w}").exists():  # write if the path does not exist
            with open(f"outputs/{source_w}", "w") as f:
                f.write(f"Class: {class_name}")
        else:  # append if the path exist
            with open(f"outputs/{source_w}", "a") as f:
                f.write(f"\n\nClass: {class_name}")

        # append class name to the front
        for function in functions:
            function_count_1 = len(functions)
            function_count_2 = 0
            print(f"Processing function {function_count_2}/{function_count_1}")

            # increment the function count and create a prompt
            function_count_2 += 1
            prompt = PromptTemplate(
                input_variables=["code"],
                template="Code: \n{code}, \nDocumentation: ",
            )

            # get the response from the model
            llm = OpenAI(temperature=0)
            response = llm(prompt.format(code=functions[function]))

            # write function name and documentation to the file
            if not Path(f"outputs/{source_w}").exists():  # write if the path does not exist
                with open(f"outputs/{source_w}", "w") as f:
                    f.write(f"Function: {functions[function]}, \nDocumentation: {response}")
            else:  # append if the path exist
                with open(f"outputs/{source_w}", "a") as f:
                    f.write(f"\n\nFunction: {functions[function]}, \nDocumentation: {response}")

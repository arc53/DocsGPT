import ast
import json
from pathlib import Path

import dotenv
from langchain.llms import OpenAI
from langchain.prompts import PromptTemplate

dotenv.load_dotenv()

ps = list(Path("inputs").glob("**/*.py"))
data = []
sources = []
for p in ps:
    with open(p) as f:
        data.append(f.read())
    sources.append(p)


def get_functions_in_class(node):
    functions = []
    functions_code = []
    for child in node.body:
        if isinstance(child, ast.FunctionDef):
            functions.append(child.name)
            functions_code.append(ast.unparse(child))

    return functions, functions_code


def get_classes_and_functions(source_code):
    tree = ast.parse(source_code)
    classes = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            class_name = node.name
            function_name, function = get_functions_in_class(node)
            # join function name and function code
            functions = dict(zip(function_name, function))
            classes[class_name] = functions
    return classes


structure_dict = {}
c1 = 0
for code in data:
    classes = get_classes_and_functions(ast.parse(code))
    source = str(sources[c1])
    structure_dict[source] = classes
    c1 += 1

# save the structure dict as json
with open('structure_dict.json', 'w') as f:
    json.dump(structure_dict, f)

if not Path("outputs").exists():
    Path("outputs").mkdir()

c1 = len(structure_dict)
c2 = 0
for source, classes in structure_dict.items():
    c2 += 1
    print(f"Processing file {c2}/{c1}")
    f1 = len(classes)
    f2 = 0
    for class_name, functions in classes.items():
        f2 += 1
        print(f"Processing class {f2}/{f1}")
        source_w = source.replace("inputs/", "")
        source_w = source_w.replace(".py", ".txt")
        if not Path(f"outputs/{source_w}").exists():
            with open(f"outputs/{source_w}", "w") as f:
                f.write(f"Class: {class_name}")
        else:
            with open(f"outputs/{source_w}", "a") as f:
                f.write(f"\n\nClass: {class_name}")
        # append class name to the front
        for function in functions:
            b1 = len(functions)
            b2 = 0
            print(f"Processing function {b2}/{b1}")
            b2 += 1
            prompt = PromptTemplate(
                input_variables=["code"],
                template="Code: \n{code}, \nDocumentation: ",
            )
            llm = OpenAI(temperature=0)
            response = llm(prompt.format(code=functions[function]))

            if not Path(f"outputs/{source_w}").exists():
                with open(f"outputs/{source_w}", "w") as f:
                    f.write(f"Function: {functions[function]}, \nDocumentation: {response}")
            else:
                with open(f"outputs/{source_w}", "a") as f:
                    f.write(f"\n\nFunction: {functions[function]}, \nDocumentation: {response}")

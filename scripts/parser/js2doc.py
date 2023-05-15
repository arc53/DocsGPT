import os

import escodegen
import esprima


def find_files(directory):
    files_list = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.js'):
                files_list.append(os.path.join(root, file))
    return files_list


def extract_functions(file_path):
    with open(file_path, 'r') as file:
        source_code = file.read()
        functions = {}
        tree = esprima.parseScript(source_code)
        for node in tree.body:
            if node.type == 'FunctionDeclaration':
                func_name = node.id.name if node.id else '<anonymous>'
                functions[func_name] = escodegen.generate(node)
            elif node.type == 'VariableDeclaration':
                for declaration in node.declarations:
                    if declaration.init and declaration.init.type == 'FunctionExpression':
                        func_name = declaration.id.name if declaration.id else '<anonymous>'
                        functions[func_name] = escodegen.generate(declaration.init)
            elif node.type == 'ClassDeclaration':
                for subnode in node.body.body:
                    if subnode.type == 'MethodDefinition':
                        func_name = subnode.key.name
                        functions[func_name] = escodegen.generate(subnode.value)
                    elif subnode.type == 'VariableDeclaration':
                        for declaration in subnode.declarations:
                            if declaration.init and declaration.init.type == 'FunctionExpression':
                                func_name = declaration.id.name if declaration.id else '<anonymous>'
                                functions[func_name] = escodegen.generate(declaration.init)
        return functions


def extract_classes(file_path):
    with open(file_path, 'r') as file:
        source_code = file.read()
        classes = {}
        tree = esprima.parseScript(source_code)
        for node in tree.body:
            if node.type == 'ClassDeclaration':
                class_name = node.id.name
                function_names = []
                for subnode in node.body.body:
                    if subnode.type == 'MethodDefinition':
                        function_names.append(subnode.key.name)
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

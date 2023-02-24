# Function name: get_functions_in_class 

Function: 
```
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
```, 
Documentation: 


get_functions_in_class(source_code, class_name)

Inputs: 
source_code (str): The source code of the program.
class_name (str): The name of the class.

Outputs: 
functions (list): A list of the functions in the class.

Description: 
This function takes in a source code and a class name and returns a list of the functions in the class. It uses the ast module to parse the source code and find the class definition. It then iterates through the body of the class and checks if each node is a function definition. If it is, it adds the name of the function to the list of functions.

# Function name: process_functions 

Function: 
```
def process_functions(functions_dict):
    c1 = len(functions_dict)
    c2 = 0
    for (source, functions) in functions_dict.items():
        c2 += 1
        print(f'Processing file {c2}/{c1}')
        f1 = len(functions)
        f2 = 0
        source_w = source.replace('inputs/', '')
        source_w = source_w.replace('.py', '.md')
        create_subfolder(source_w)
        for (name, function) in functions.items():
            f2 += 1
            print(f'Processing function {f2}/{f1}')
            response = generate_response(function)
            write_output_file(source_w, name, function, response)
```, 
Documentation: 


This function takes in a dictionary of functions and processes them. It takes the source file and the functions from the dictionary and creates a subfolder for the source file. It then generates a response for each function and writes the output file. The output file contains the function, the response, and the source file.

# Function name: get_functions_in_class 

Function: 
```
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
```, 
Documentation: 


get_functions_in_class(source_code, class_name)

Inputs: 
source_code (str): The source code of the program.
class_name (str): The name of the class.

Outputs: 
functions (list): A list of the functions in the class.

Description: 
This function takes in a source code and a class name and returns a list of the functions in the class. It uses the ast module to parse the source code and find the class definition. It then iterates through the body of the class and checks if each node is a function definition. If it is, it adds the name of the function to the list of functions.

# Function name: process_functions 

Function: 
```
def process_functions(functions_dict):
    c1 = len(functions_dict)
    c2 = 0
    for (source, functions) in functions_dict.items():
        c2 += 1
        print(f'Processing file {c2}/{c1}')
        f1 = len(functions)
        f2 = 0
        source_w = source.replace('inputs/', '')
        source_w = source_w.replace('.py', '.md')
        create_subfolder(source_w)
        for (name, function) in functions.items():
            f2 += 1
            print(f'Processing function {f2}/{f1}')
            response = generate_response(function)
            write_output_file(source_w, name, function, response)
```, 
Documentation: 


This function takes in a dictionary of functions and processes them. It takes the source file and the functions from the dictionary and creates a subfolder for the source file. It then generates a response for each function and writes the output file for each function.

# Function name: get_functions_in_class 

Function: 
```
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
```, 
Documentation: 


get_functions_in_class(source_code, class_name)

Inputs: 
source_code (str): The source code of the program.
class_name (str): The name of the class.

Outputs: 
functions (list): A list of the functions in the class.

Description: 
This function takes in a source code and a class name and returns a list of the functions in the class. It uses the ast module to parse the source code and find the class definition. It then iterates through the body of the class and checks if each node is a function definition. If it is, it adds the name of the function to the list of functions.

# Function name: process_functions 

Function: 
```
def process_functions(functions_dict):
    c1 = len(functions_dict)
    c2 = 0
    for (source, functions) in functions_dict.items():
        c2 += 1
        print(f'Processing file {c2}/{c1}')
        f1 = len(functions)
        f2 = 0
        source_w = source.replace('inputs/', '')
        source_w = source_w.replace('.py', '.md')
        create_subfolder(source_w)
        for (name, function) in functions.items():
            f2 += 1
            print(f'Processing function {f2}/{f1}')
            response = generate_response(function)
            write_output_file(source_w, name, function, response)
```, 
Documentation: 


This function takes in a dictionary of functions and processes them. It takes the source file and the functions from the dictionary and creates a subfolder for the source file. It then generates a response for each function and writes the output file for each function.
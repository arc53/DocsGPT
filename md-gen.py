import os

def create_markdown_from_directory(directory=".", output_file="combined.md"):
    """
    Recursively traverses the given directory, reads all files (ignoring files/folders in ignore_list),
    and creates a single markdown file containing the contents of each file, prefixed with the
    relative path of the file.

    Args:
        directory (str): The directory to traverse. Defaults to the current directory.
        output_file (str): The name of the output markdown file. Defaults to 'combined.md'.
    """
    ignore_list = [
        "node_modules", "__pycache__", ".git", ".DS_Store", "inputs", "indexes",
        "model", "models", ".venv", "temp", ".pytest_cache", ".ruff_cache",
        "extensions", "dir_tree.py", "map.txt", "signal-desktop-keyring.gpg",
        ".husky", ".next", "docs", "index.pkl", "index.faiss", "assets", "fonts", "public",
        "yarn.lock", "package-lock.json",
        ]

    with open(output_file, "w", encoding="utf-8") as outfile:
        for root, dirs, files in os.walk(directory):
            # Filter out directories in ignore_list so they won't be traversed
            dirs[:] = [d for d in dirs if d not in ignore_list]
            
            for filename in files:
                if filename in ignore_list:
                    continue
                filepath = os.path.join(root, filename)
                
                try:
                    with open(filepath, "r", encoding="utf-8") as infile:
                        content = infile.read()
                    
                    # Get a relative path to better indicate file location
                    rel_path = os.path.relpath(filepath, directory)
                    outfile.write(f"## File: {rel_path}\n\n")
                    outfile.write(content)
                    outfile.write("\n\n---\n\n")  # Separator between files

                except Exception as e:
                    print(f"Error processing file {filepath}: {e}")

    print(f"Successfully created {output_file}")

if __name__ == "__main__":
    create_markdown_from_directory()

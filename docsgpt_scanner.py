import os
import argparse
from pathlib import Path
import datetime
import re
import json

class DocsGPTDocumentationGenerator:
    def __init__(self, root_dir, config=None):
        """
        Initialize the documentation generator with customized settings for DocsGPT.
        
        Args:
            root_dir (str): The path to the root directory of the project.
            config (dict, optional): Configuration overrides.
        """
        self.root_dir = os.path.abspath(root_dir)
        
        # Default configuration optimized for DocsGPT
        self.config = {
            # Directories to exclude completely
            'excluded_dirs': [
                '__pycache__', 'venv', '.venv', 'node_modules', '.git', '.idea', '.vscode',
                'dist', 'build', 'model', 'temp', 'indexes', 'model', 'postgres_data',
                'logs', 'out', 'vectors'
            ],
            
            # File patterns to exclude
            'excluded_patterns': [
                '*.pyc', '*.bin', '*.faiss', '*.pkl', '*.so', '*.o', 
                '*.jpg', '*.jpeg', '*.png', '*.gif', '*.webp', '*.ico', '*.lock',
                '*.pdf'  # Exclude PDFs as they're just data in your project
            ],
            
            # Files that should always be included despite other exclusions
            'always_include': [
                'README.md', 'LICENSE', 'CONTRIBUTING.md', 'requirements.txt',
                'package.json', 'Dockerfile', 'docker-compose*.yaml', 'docker-compose*.yml'
            ],
            
            # Core code directories to focus on
            'core_dirs': [
                'application', 'frontend/src', 'extensions', 'docs'
            ],
            
            # File types to include content in documentation
            'content_file_types': [
                '.py', '.js', '.jsx', '.ts', '.tsx', '.md', '.txt',
                '.yaml', '.yml', '.json', '.dockerfile'
            ],
            
            # Max file size to include content (100KB)
            'max_content_size': 100 * 1024,
            
            # Max number of files to include full content for each directory
            'max_files_per_dir': 5,
            
            # Max characters to show in file previews
            'preview_length': 500
        }
        
        # Override config with provided values
        if config:
            self.config.update(config)
    
    def should_exclude(self, path):
        """
        Determine if a path should be excluded from the documentation.
        
        Args:
            path (str): The path to check.
            
        Returns:
            bool: True if the path should be excluded, False otherwise.
        """
        name = os.path.basename(path)
        
        # Always include certain files
        for pattern in self.config['always_include']:
            if self._match_pattern(name, pattern):
                return False
        
        # Check if it's in excluded directories
        parts = Path(path).relative_to(self.root_dir).parts
        for part in parts:
            for excluded_dir in self.config['excluded_dirs']:
                if self._match_pattern(part, excluded_dir):
                    return True
        
        # Check excluded patterns
        for pattern in self.config['excluded_patterns']:
            if self._match_pattern(name, pattern):
                return True
        
        # Exclude hidden files
        if name.startswith('.') and name not in ['.env.example']:
            return True
        
        return False
    
    def _match_pattern(self, name, pattern):
        """
        Check if a name matches a pattern with simple wildcard support.
        
        Args:
            name (str): The name to check.
            pattern (str): The pattern to match against.
            
        Returns:
            bool: True if the name matches the pattern, False otherwise.
        """
        if pattern.startswith('*.'):
            # Extension pattern
            return name.endswith(pattern[1:])
        elif '*' in pattern:
            # Convert to regex pattern
            regex_pattern = pattern.replace('.', r'\.').replace('*', '.*')
            return bool(re.match(f"^{regex_pattern}$", name))
        else:
            # Exact match
            return name == pattern
    
    def scan_directory(self):
        """
        Scan the directory and build a structure representation.
        
        Returns:
            dict: A dictionary representation of the project structure
        """
        structure = {}
        
        for root, dirs, files in os.walk(self.root_dir):
            # Skip excluded directories
            dirs[:] = [d for d in dirs if not self.should_exclude(os.path.join(root, d))]
            
            # Get the relative path from the root directory
            rel_path = os.path.relpath(root, self.root_dir)
            if rel_path == '.':
                rel_path = ''
            
            # Filter files based on excluded patterns
            filtered_files = [file for file in files if not self.should_exclude(os.path.join(root, file))]
            
            # Add directory and its files to the structure
            if rel_path:
                current_level = structure
                for part in rel_path.split(os.path.sep):
                    if part not in current_level:
                        current_level[part] = {}
                    current_level = current_level[part]
                current_level['__files__'] = filtered_files
            else:
                structure['__files__'] = filtered_files
        
        return structure
    
    def print_structure(self, structure=None, indent=0, is_last=True, prefix="", file=None):
        """
        Print the directory structure in a tree-like format.
        
        Args:
            structure (dict): Dictionary representing the directory structure.
            indent (int): Current indentation level.
            is_last (bool): Whether this is the last item in its parent.
            prefix (str): Prefix for the current line.
            file: File object to write to.
        """
        if structure is None:
            # First call, print the root directory name
            structure = self.scan_directory()
            root_name = os.path.basename(self.root_dir) + "/"
            line = root_name
            if file:
                file.write(f"{line}\n")
            print(line)
        
        # Print files
        if '__files__' in structure:
            files = structure.pop('__files__')
            for i, file_name in enumerate(sorted(files)):
                is_last_file = (i == len(files) - 1) and len(structure) == 0
                connector = "└── " if is_last_file else "├── "
                line = f"{prefix}{connector}{file_name}"
                if file:
                    file.write(f"{line}\n")
                print(line)
        
        # Process directories
        items = list(sorted(structure.items()))
        for i, (dir_name, contents) in enumerate(items):
            is_last_dir = i == len(items) - 1
            connector = "└── " if is_last_dir else "├── "
            line = f"{prefix}{connector}{dir_name}/"
            if file:
                file.write(f"{line}\n")
            print(line)
            
            new_prefix = prefix + ("    " if is_last_dir else "│   ")
            self.print_structure(contents, indent + 1, is_last_dir, new_prefix, file)
    
    def _get_file_language(self, file_path):
        """
        Determine the language of a file for code block formatting.
        
        Args:
            file_path (str): Path to the file.
            
        Returns:
            str: Language identifier for markdown code block.
        """
        ext = os.path.splitext(file_path)[1].lower()
        name = os.path.basename(file_path)
        
        # Map file extensions to language identifiers
        ext_to_lang = {
            '.py': 'python',
            '.js': 'javascript',
            '.jsx': 'jsx',
            '.ts': 'typescript',
            '.tsx': 'tsx',
            '.html': 'html',
            '.css': 'css',
            '.scss': 'scss',
            '.md': 'markdown',
            '.json': 'json',
            '.yaml': 'yaml',
            '.yml': 'yaml',
            '.sh': 'bash'
        }
        
        # Special files
        if name in ['Dockerfile']:
            return 'dockerfile'
        elif name in ['docker-compose.yml', 'docker-compose.yaml']:
            return 'yaml'
        elif name in ['Makefile']:
            return 'makefile'
        elif name in ['.gitignore', 'requirements.txt', '.env.example']:
            return ''  # Plain text
        
        return ext_to_lang.get(ext, '')
    
    def should_include_content(self, file_path):
        """
        Check if a file's content should be included in the documentation.
        
        Args:
            file_path (str): The path to the file.
            
        Returns:
            bool: True if content should be included, False otherwise.
        """
        # Check file size
        if os.path.getsize(file_path) > self.config['max_content_size']:
            return False
        
        # Check file extension
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in self.config['content_file_types']:
            return False
        
        # Check if file is in a core directory
        rel_path = os.path.relpath(file_path, self.root_dir)
        for core_dir in self.config['core_dirs']:
            if rel_path.startswith(core_dir):
                return True
        
        # Include any README or key configuration files
        name = os.path.basename(file_path)
        if any(self._match_pattern(name, pattern) for pattern in self.config['always_include']):
            return True
        
        return False
    
    def count_files_by_type(self):
        """
        Count the number of files by type in the project.
        
        Returns:
            dict: A dictionary mapping file extensions to counts.
        """
        ext_counts = {}
        
        for root, _, files in os.walk(self.root_dir):
            if self.should_exclude(root):
                continue
                
            for file in files:
                file_path = os.path.join(root, file)
                if self.should_exclude(file_path):
                    continue
                
                ext = os.path.splitext(file)[1].lower()
                if not ext:
                    ext = '(no extension)'
                
                ext_counts[ext] = ext_counts.get(ext, 0) + 1
        
        return ext_counts
    
    def generate_code_snippets(self, structure=None, path="", snippets=None):
        """
        Generate representative code snippets from the project.
        
        Args:
            structure (dict): Project structure dictionary.
            path (str): Current path in the structure.
            snippets (dict): Dictionary to store snippets by directory.
            
        Returns:
            dict: Dictionary mapping directories to lists of file snippets.
        """
        if snippets is None:
            snippets = {}
            structure = self.scan_directory()
        
        # Process files in the current directory
        if '__files__' in structure:
            files = structure.pop('__files__')
            dir_snippets = []
            
            # Sort files to prioritize key files
            sorted_files = sorted(files, key=lambda f: f.startswith(('README', 'main', 'app')) and not f.startswith('.'), reverse=True)
            
            for file in sorted_files[:self.config['max_files_per_dir']]:
                file_path = os.path.join(self.root_dir, path, file)
                
                if self.should_include_content(file_path):
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                            content = f.read(self.config['preview_length'])
                            too_long = len(content) >= self.config['preview_length']
                            
                            dir_snippets.append({
                                'name': file,
                                'path': os.path.join(path, file),
                                'language': self._get_file_language(file_path),
                                'content': content + ('...' if too_long else ''),
                                'full_path': file_path
                            })
                    except Exception as e:
                        # Skip files that can't be read
                        pass
            
            if dir_snippets:
                snippets[path or '.'] = dir_snippets
        
        # Process subdirectories
        for dir_name, contents in structure.items():
            self.generate_code_snippets(contents, os.path.join(path, dir_name), snippets)
        
        return snippets
    
    def find_important_files(self):
        """
        Find and return a list of important files in the project.
        
        Returns:
            list: List of important file paths.
        """
        important_files = []
        
        # Files to look for in any directory
        common_important_files = [
            'README.md', 'Dockerfile', 'docker-compose.yml', 'docker-compose.yaml',
            'requirements.txt', 'setup.py', 'package.json', 'app.py', 'main.py',
            'settings.py', 'config.py', 'wsgi.py', '.env.example'
        ]
        
        for root, _, files in os.walk(self.root_dir):
            if self.should_exclude(root):
                continue
                
            for file in files:
                if file in common_important_files:
                    important_files.append(os.path.join(root, file))
        
        return important_files
    
    def generate_markdown(self, output_file):
        """
        Generate a comprehensive markdown document for the DocsGPT project.
        
        Args:
            output_file (str): Path to the output markdown file.
        """
        structure = self.scan_directory()
        ext_counts = self.count_files_by_type()
        important_files = self.find_important_files()
        snippets = self.generate_code_snippets()
        
        with open(output_file, 'w', encoding='utf-8') as md_file:
            # Title and metadata
            md_file.write(f"# DocsGPT Project Documentation\n\n")
            md_file.write(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
            
            # Project Overview
            md_file.write("## 1. Project Overview\n\n")
            
            # Try to include README content
            readme_path = os.path.join(self.root_dir, "README.md")
            if os.path.exists(readme_path):
                try:
                    with open(readme_path, 'r', encoding='utf-8', errors='replace') as readme:
                        content = readme.read()
                        md_file.write("### From README.md\n\n")
                        md_file.write(f"{content}\n\n")
                except Exception:
                    md_file.write("*Error reading README.md*\n\n")
            
            # Project stats
            md_file.write("### Project Statistics\n\n")
            
            # Count directories and files
            total_dirs = 0
            total_files = 0
            for root, dirs, files in os.walk(self.root_dir):
                if not self.should_exclude(root):
                    total_dirs += sum(1 for d in dirs if not self.should_exclude(os.path.join(root, d)))
                    total_files += sum(1 for f in files if not self.should_exclude(os.path.join(root, f)))
            
            md_file.write(f"- **Total Directories:** {total_dirs}\n")
            md_file.write(f"- **Total Files:** {total_files}\n\n")
            
            md_file.write("#### File Types\n\n")
            for ext, count in sorted(ext_counts.items(), key=lambda x: x[1], reverse=True)[:15]:
                md_file.write(f"- **{ext}:** {count} files\n")
            md_file.write("\n")
            
            # Directory Structure
            md_file.write("## 2. Directory Structure\n\n")
            md_file.write("```\n")
            self.print_structure(file=md_file)
            md_file.write("```\n\n")
            
            # Key Components
            md_file.write("## 3. Key Components\n\n")
            
            # Application component
            md_file.write("### 3.1. Application Core\n\n")
            if 'application' in snippets:
                md_file.write("The application core contains the main backend logic for DocsGPT.\n\n")
                for snippet in snippets['application'][:3]:
                    md_file.write(f"#### {snippet['path']}\n\n")
                    md_file.write(f"```{snippet['language']}\n{snippet['content']}\n```\n\n")
            
            # Frontend component
            md_file.write("### 3.2. Frontend\n\n")
            frontend_snippets = [s for path, files in snippets.items() 
                               for s in files if path.startswith('frontend/src')]
            if frontend_snippets:
                md_file.write("The frontend is built with React and provides the user interface.\n\n")
                for snippet in frontend_snippets[:3]:
                    md_file.write(f"#### {snippet['path']}\n\n")
                    md_file.write(f"```{snippet['language']}\n{snippet['content']}\n```\n\n")
            
            # Extensions
            md_file.write("### 3.3. Extensions\n\n")
            extension_snippets = [s for path, files in snippets.items() 
                                for s in files if path.startswith('extensions')]
            if extension_snippets:
                md_file.write("DocsGPT includes various extensions for different platforms.\n\n")
                for snippet in extension_snippets[:3]:
                    md_file.write(f"#### {snippet['path']}\n\n")
                    md_file.write(f"```{snippet['language']}\n{snippet['content']}\n```\n\n")
            
            # Configuration Files
            md_file.write("## 4. Configuration Files\n\n")
            
            # Docker files
            md_file.write("### 4.1. Docker Configuration\n\n")
            docker_files = [f for f in important_files if os.path.basename(f) in 
                          ['Dockerfile', 'docker-compose.yml', 'docker-compose.yaml']]
            
            for file_path in docker_files:
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                        content = f.read()
                        rel_path = os.path.relpath(file_path, self.root_dir)
                        md_file.write(f"#### {rel_path}\n\n")
                        
                        lang = 'dockerfile' if os.path.basename(file_path) == 'Dockerfile' else 'yaml'
                        md_file.write(f"```{lang}\n{content}\n```\n\n")
                except Exception as e:
                    md_file.write(f"*Error reading {os.path.relpath(file_path, self.root_dir)}: {e}*\n\n")
            
            # Requirements and package files
            md_file.write("### 4.2. Dependencies\n\n")
            dep_files = [f for f in important_files if os.path.basename(f) in 
                       ['requirements.txt', 'package.json']]
            
            for file_path in dep_files:
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                        content = f.read()
                        rel_path = os.path.relpath(file_path, self.root_dir)
                        md_file.write(f"#### {rel_path}\n\n")
                        
                        lang = 'json' if file_path.endswith('.json') else ''
                        md_file.write(f"```{lang}\n{content}\n```\n\n")
                except Exception as e:
                    md_file.write(f"*Error reading {os.path.relpath(file_path, self.root_dir)}: {e}*\n\n")
            
            # Environment files
            env_files = [f for f in important_files if os.path.basename(f) == '.env.example']
            if env_files:
                md_file.write("### 4.3. Environment Configuration\n\n")
                
                for file_path in env_files:
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                            content = f.read()
                            rel_path = os.path.relpath(file_path, self.root_dir)
                            md_file.write(f"#### {rel_path}\n\n")
                            md_file.write(f"```\n{content}\n```\n\n")
                    except Exception as e:
                        md_file.write(f"*Error reading {os.path.relpath(file_path, self.root_dir)}: {e}*\n\n")
            
            # API Documentation (if we can find routes)
            md_file.write("## 5. API Documentation\n\n")
            api_files = []
            for root, _, files in os.walk(os.path.join(self.root_dir, 'application/api')):
                if self.should_exclude(root):
                    continue
                    
                for file in files:
                    if file == 'routes.py':
                        api_files.append(os.path.join(root, file))
            
            if api_files:
                md_file.write("### API Routes\n\n")
                for file_path in api_files[:5]:  # Limit to 5 route files
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                            content = f.read()
                            rel_path = os.path.relpath(file_path, self.root_dir)
                            md_file.write(f"#### {rel_path}\n\n")
                            md_file.write(f"```python\n{content}\n```\n\n")
                    except Exception as e:
                        md_file.write(f"*Error reading {os.path.relpath(file_path, self.root_dir)}: {e}*\n\n")
            
            # Conclusion
            md_file.write("## 6. Additional Information\n\n")
            md_file.write("This documentation provides an overview of the DocsGPT project structure and key components. "
                         "For more detailed information, please refer to the official documentation and code comments.\n\n")
            
            md_file.write("### License\n\n")
            license_path = os.path.join(self.root_dir, "LICENSE")
            if os.path.exists(license_path):
                try:
                    with open(license_path, 'r', encoding='utf-8', errors='replace') as f:
                        content = f.read(500)  # Just read the beginning of the license
                        md_file.write(f"```\n{content}...\n```\n\n")
                except Exception:
                    md_file.write("*Error reading LICENSE file*\n\n")
            
            # Generation metadata
            md_file.write("---\n\n")
            md_file.write(f"*Documentation generated on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n")
            md_file.write(f"*Generator: DocsGPT Project Documentation Generator*\n")


def main():
    parser = argparse.ArgumentParser(description='DocsGPT Project Documentation Generator')
    
    parser.add_argument('--root', '-r', type=str, default='.',
                        help='Root directory of the project (default: current directory)')
    
    parser.add_argument('--output', '-o', type=str,
                        help='Output markdown file (default: project_name_docs.md in the root directory)')
    
    parser.add_argument('--exclude-dirs', '-e', type=str, nargs='+',
                        help='Additional directories to exclude')
    
    parser.add_argument('--exclude-files', '-ef', type=str, nargs='+',
                        help='Additional file patterns to exclude')
    
    parser.add_argument('--include-files', '-if', type=str, nargs='+',
                        help='Files to always include despite exclusions')
    
    parser.add_argument('--core-dirs', '-c', type=str, nargs='+',
                        help='Core directories to focus on for code snippets')
    
    parser.add_argument('--config-file', '-cf', type=str,
                        help='Path to JSON configuration file')
    
    parser.add_argument('--tree-only', action='store_true',
                        help='Only print the directory tree structure, do not generate documentation')
    
    args = parser.parse_args()
    
    # Get absolute path of the root directory
    root_dir = os.path.abspath(args.root)
    
    # Load configuration from file if provided
    config = None
    if args.config_file:
        try:
            with open(args.config_file, 'r') as f:
                config = json.load(f)
        except Exception as e:
            print(f"Error loading configuration file: {e}")
            return
    else:
        # Build configuration from command line arguments
        config = {}
        if args.exclude_dirs:
            config['excluded_dirs'] = args.exclude_dirs
        if args.exclude_files:
            config['excluded_patterns'] = args.exclude_files
        if args.include_files:
            config['always_include'] = args.include_files
        if args.core_dirs:
            config['core_dirs'] = args.core_dirs
    
    # Create the generator
    generator = DocsGPTDocumentationGenerator(root_dir=root_dir, config=config)
    
    if args.tree_only:
        # Just print the tree structure
        print(f"Directory structure for: {root_dir}\n")
        generator.print_structure()
    else:
        # Generate full documentation
        output_file = args.output
        if not output_file:
            project_name = os.path.basename(root_dir)
            output_file = os.path.join(root_dir, f"{project_name}_documentation.md")
        
        print(f"Generating documentation for {root_dir}...")
        generator.generate_markdown(output_file)
        print(f"Documentation saved to: {output_file}")


if __name__ == "__main__":
    main()
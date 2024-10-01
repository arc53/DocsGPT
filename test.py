from pathlib import Path
from application.parser.file.tabular_parser import ExcelParser,PandasCSVParser

# Define the path to the .xlsx file
file_path = Path("/home/dev523/DocsGPT/Ledgers in Default Template.xlsx")
parser = ExcelParser(concat_rows=True, pandas_config={})

# Initialize the ExcelParser
# file_path = Path("/home/dev523/DocsGPT/mlb_teams_2012.csv")
# parser = PandasCSVParser(concat_rows=True, pandas_config={})



# Initialize the parser configuration (this can be customized if needed)
parser.init_parser()

# Check if the parser config is set (this is optional)
if parser.parser_config_set:
    print("Parser config has been set.")

# Parse the Excel file
parsed_data = parser.parse_file(file_path)
print(parsed_data)



"""HTML parser.

Contains parser for html files.

"""
import re
from pathlib import Path
from typing import Dict, Union

from parser.file.base_parser import BaseParser

class HTMLParser(BaseParser):
    """HTML parser."""

    def _init_parser(self) -> Dict:
        """Init parser."""
        return {}

    def parse_file(self, file: Path, errors: str = "ignore") -> Union[str, list[str]]:
        """Parse file.

            Returns:
            Union[str, List[str]]: a string or a List of strings.
        """
        try:
            import unstructured
        except ImportError:
            raise ValueError("unstructured package is required to parse HTML files.")
        from unstructured.partition.html import partition_html
        from unstructured.staging.base import convert_to_isd
        from unstructured.cleaners.core import clean

        # Using the unstructured library to convert the html to isd format
        # isd sample : isd = [
                            #   {"text": "My Title", "type": "Title"},
                            #   {"text": "My Narrative", "type": "NarrativeText"}
                            # ]
        with open(file, "r", encoding="utf-8") as fp:
            elements = partition_html(file=fp)
            isd = convert_to_isd(elements)  

        # Removing non ascii charactwers from isd_el['text']
        for isd_el in isd:
            isd_el['text'] = isd_el['text'].encode("ascii", "ignore").decode()

        # Removing all the \n characters from isd_el['text'] using regex and replace with single space
        # Removing all the extra spaces  from isd_el['text'] using regex and replace with single space
        for isd_el in isd:
            isd_el['text'] = re.sub(r'\n', ' ', isd_el['text'], flags=re.MULTILINE|re.DOTALL)
            isd_el['text'] = re.sub(r"\s{2,}"," ", isd_el['text'], flags=re.MULTILINE|re.DOTALL)

        # more cleaning: extra_whitespaces, dashes, bullets, trailing_punctuation
        for isd_el in isd:
            clean(isd_el['text'], extra_whitespace=True, dashes=True, bullets=True, trailing_punctuation=True )

        # Creating a list of all the indexes of isd_el['type'] = 'Title'
        title_indexes = [i for i,isd_el in enumerate(isd) if isd_el['type'] == 'Title']

        # Creating 'Chunks' - List of lists of strings 
        # each list starting with with isd_el['type'] = 'Title' and all the data till the next 'Title'
        # Each Chunk can be thought of as an individual set of data, which can be sent to the model
        # Where Each Title is grouped together with the data under it

        Chunks = [[]]
        final_chunks = list(list())

        for i,isd_el in enumerate(isd):
            if i in title_indexes:
                Chunks.append([])
            Chunks[-1].append(isd_el['text'])

        # Removing all the chunks with sum of lenth of all the strings in the chunk < 25 #TODO: This value can be an user defined variable
        for chunk in Chunks:
            # sum of lenth of all the strings in the chunk
            sum = 0
            sum += len(str(chunk))
            if sum < 25:
                Chunks.remove(chunk)
            else :         
                # appending all the approved chunks to final_chunks as a single string       
                final_chunks.append(" ".join([str(item) for item in chunk]))
        return final_chunks

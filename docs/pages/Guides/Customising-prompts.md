# Customizing the Main Prompt

To customize the main prompt for DocsGPT, follow these steps:

1. Navigate to `/application/prompt/combine_prompt.txt`.

2. Edit the `combine_prompt.txt` file to modify the prompt text. You can experiment with different phrasings and structures to see how the model responds.

## Example Prompt Modification

**Original Prompt:**
```markdown
QUESTION: How to merge tables in pandas?
=========
Content: pandas provides various facilities for easily combining together Series or DataFrame with various kinds of set logic for the indexes and relational algebra functionality in the case of join / merge-type operations.
Source: 28-pl
Content: pandas provides a single function, merge(), as the entry point for all standard database join operations between DataFrame or named Series objects: \n\npandas.merge(left, right, how='inner', on=None, left_on=None, right_on=None, left_index=False, right_index=False, sort=False, suffixes=('_x', '_y'), copy=True, indicator=False, validate=None)
Source: 30-pl
=========
FINAL ANSWER: To merge two tables in pandas, you can use the pd.merge() function. The basic syntax is: \n\npd.merge(left, right, on, how) \n\nwhere left and right are the two tables to merge, on is the column to merge on, and how is the type of merge to perform. \n\nFor example, to merge the two tables df1 and df2 on the column 'id', you can use: \n\npd.merge(df1, df2, on='id', how='inner')
SOURCES: 28-pl 30-pl


## Modified Prompt (for illustration):

QUESTION: Explain the concept of pandas merge in Python.
=========
Content: The pandas merge function in Python allows you to combine DataFrame objects by performing SQL-style joins. It is a powerful tool for data manipulation and analysis.
Source: Official pandas documentation
Content: You can use the merge function with various options such as 'how,' 'on,' 'left_on,' and 'right_on' to control how the merging is done.
Source: Data science tutorial blog
=========
FINAL ANSWER: To perform a pandas merge in Python, use the `pd.merge()` function. This function takes two DataFrames as input and merges them based on the specified columns. For example, to merge DataFrames `df1` and `df2` on the 'key' column, you can use: `pd.merge(df1, df2, on='key', how='inner')`.
SOURCES: Official pandas documentation, Data science tutorial blog


## Conclusion

Customizing the main prompt for DocsGPT allows you to tailor the AI's responses to your unique requirements. Whether you need in-depth explanations, code examples, or specific insights, you can achieve it by modifying the main prompt. Remember to experiment and fine-tune your prompts to get the best results.


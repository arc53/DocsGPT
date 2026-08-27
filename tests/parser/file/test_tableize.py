"""Tests for the dot-leader/whitespace table reconstruction (``ANYDOC_TABLEIZE``)."""
from application.parser.file.tableize import tableize

DOT_LEADER = """Revenues
Insurance premiums ............ 83,431 77,731
Sales and service revenues ........ 24,660 23,406
Freight rail transportation ......... 22,341 23,852
Total revenues 130,432 124,989
"""


def test_dot_leader_run_becomes_table():
    out = tableize(DOT_LEADER)
    assert "| Insurance premiums | 83,431 | 77,731 |" in out
    assert "| Total revenues | 130,432 | 124,989 |" in out
    assert "| --- |" in out
    assert "Revenues" in out  # heading line untouched


def test_whitespace_only_rows_convert_too():
    md = "Alpha 1 2\nBeta 3 4\nGamma 5 6\n"
    out = tableize(md)
    assert "| Alpha | 1 | 2 |" in out


def test_currency_symbol_merges_with_number():
    md = "Cash $ 1,234 900\nDebt $ 2,000 1,500\nEquity $ 900 800\n"
    out = tableize(md)
    assert "| Cash | $1,234 | 900 |" in out


def test_parenthesised_negatives_and_dash():
    md = "Losses (30) —\nGains (12) —\nNet (42) —\n"
    out = tableize(md)
    assert "| Losses | (30) | — |" in out


def test_short_run_is_left_alone():
    md = "Alpha 1 2\nBeta 3 4\n"
    assert "|" not in tableize(md)


def test_mixed_widths_are_left_alone():
    md = "Alpha 1 2\nBeta 3\nGamma 5 6\n"
    assert "|" not in tableize(md)


def test_prose_with_numbers_is_left_alone():
    md = "The division shipped 47 releases in 2023.\nIt hired 12 engineers this year alone.\nRevenue grew by a factor of 3 since 2019.\n"
    assert "|" not in tableize(md)


def test_min_rows_boundary():
    two = "A 1 2\nB 3 4\n"
    three = two + "C 5 6\n"
    assert "|" not in tableize(two, min_rows=3)
    assert "|" in tableize(three, min_rows=3)


def test_pipe_in_label_is_escaped():
    md = "Assets | current 1,234 900\nDebt 2,000 1,500\nEquity 900 800\n"
    out = tableize(md)
    assert "| Assets \\| current | 1,234 | 900 |" in out


def test_dollar_prefixed_word_is_not_a_value():
    md = "Alpha $TBD 2\nBeta $TBD 4\nGamma $TBD 6\n"
    assert "|" not in tableize(md)


def test_non_table_text_passes_through_verbatim():
    """Only the trailing newline may differ (splitlines/join round-trip)."""
    md = "# Heading\n\nA paragraph with no numbers.\n\n- a list item\n"
    assert tableize(md) == md.rstrip("\n")

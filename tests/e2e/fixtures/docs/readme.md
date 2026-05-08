# Introduction to UTF-8 Encoding

UTF-8 is a variable-width character encoding capable of representing every
character in the Unicode standard. It was designed as a backward-compatible
replacement for ASCII, and it has become the dominant encoding for text on
the web and in most modern file formats.

## How UTF-8 Works

UTF-8 encodes each Unicode code point as one to four bytes. The number of
bytes used depends on the numeric value of the code point. Characters in the
ASCII range use a single byte identical to the ASCII byte, which is why any
valid ASCII text is also a valid UTF-8 text. Higher code points use a lead
byte that signals how many continuation bytes follow, and continuation bytes
always begin with the bit pattern ten.

The design has a number of useful properties. Byte boundaries cannot be
mistaken for character boundaries, because continuation bytes never look like
lead bytes. A corrupted or truncated stream can be resynchronised by scanning
forward to the next byte that is not a continuation byte. Sorting UTF-8
strings lexicographically by byte value produces the same order as sorting by
Unicode code point.

## Example

Below is a short Python snippet that encodes and decodes a UTF-8 string.

```python
text = "hello"
data = text.encode("utf-8")
again = data.decode("utf-8")
assert again == text
```

## Key Advantages

- Compact for Latin-script text, because ASCII characters use only one byte.
- Self-synchronising, which makes error recovery straightforward.
- A strict superset of ASCII, so legacy ASCII tools handle it gracefully.
- Well supported by every major programming language and operating system.
- Avoids the byte-order ambiguity that affects UTF-16 and UTF-32.

UTF-8 is recommended by the Internet Engineering Task Force as the default
encoding for web content, email headers, and most other text-based protocols.
Using it consistently across an application removes an entire class of
encoding-related bugs.

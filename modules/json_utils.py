# Standard library imports
import re
import json
import ast

class JSONParsingError(ValueError):
    """Custom exception for errors during JSON extraction and parsing."""
    def __init__(self, message, text=None, original_exception=None):
        self.text = text
        self.original_exception = original_exception
        full_message = message
        if text:
            pos = getattr(original_exception, 'pos', None)
            if pos is not None:
                start, end = max(0, pos - 40), min(len(text), pos + 40)
                snippet, pointer = text[start:end].replace('\n', '\\n'), " " * (pos - start) + "^"
                full_message += f"\nContext around error (pos {pos}):\n{snippet}\n{pointer}"
            else:
                full_message += f"\nText snippet: {text[:200]}..."
        if original_exception: full_message += f"\nOriginal error: {original_exception}"
        super().__init__(full_message)

def _find_json_candidate(text: str) -> str | None:
    """Finds the most likely JSON string candidate from raw text returned by an LLM."""
    match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\}|\[[\s\S]*?\])\s*```", text, re.DOTALL)
    if match:
        return match.group(1)

    last_brace = text.rfind('{')
    last_bracket = text.rfind('[')

    if last_brace == -1 and last_bracket == -1:
        return None

    start_pos = max(last_brace, last_bracket)
    start_char = text[start_pos]
    end_char = '}' if start_char == '{' else ']'

    balance, in_string = 1, False
    for i in range(start_pos + 1, len(text)):
        char = text[i]
        if char == '"' and (i == 0 or text[i-1] != '\\'):
            in_string = not in_string
        if not in_string:
            if char == start_char: balance += 1
            elif char == end_char: balance -= 1
        if balance == 0:
            return text[start_pos : i + 1]
    return None

def _escape_newlines_in_strings(text: str):
    """A generator that yields characters, escaping newlines only when inside a string."""
    in_string, is_escaped = False, False
    for char in text:
        if char == '"' and not is_escaped:
            in_string = not in_string
        if in_string and not is_escaped:
            if char == '\n':
                yield '\\n'
                continue
            if char == '\r':
                continue
        yield char
        is_escaped = (char == '\\' and not is_escaped)

def _clean_json_string(json_str: str) -> str:
    """Cleans a JSON string candidate to fix common, non-standard syntax produced by LLMs."""
    cleaned_str = re.sub(r'</?ref>', '', json_str)
    cleaned_str = re.sub(r"^\s*//.*$", "", json_str, flags=re.MULTILINE)
    cleaned_str = re.sub(r'/\*[\s\S]*?\*/', '', cleaned_str)
    cleaned_str = re.sub(r"([{,]\\s*)([a-zA-Z0-9_.-]+)(\\s*:)", r'\1"\2"\3', cleaned_str)
    cleaned_str = re.sub(r'(:\s*)\'([^\']*)\'', r'\1"\2"', cleaned_str)
    cleaned_str = re.sub(r",\s*([}\]])", r"\1", cleaned_str)
    cleaned_str = re.sub(r'\bTrue\b', 'true', cleaned_str, flags=re.IGNORECASE)
    cleaned_str = re.sub(r'\bFalse\b', 'false', cleaned_str, flags=re.IGNORECASE)
    cleaned_str = re.sub(r'\bNone\b', 'null', cleaned_str, flags=re.IGNORECASE)
    return "".join(_escape_newlines_in_strings(cleaned_str)).strip()

def _extract_and_parse_json(text: str):
    """Extracts and parses a JSON object from a string that may contain other text."""
    if not text or not text.strip(): raise JSONParsingError("Input text is empty or contains only whitespace.")
    json_str_candidate = _find_json_candidate(text)
    text_to_parse, source_label = (json_str_candidate, "extracted JSON candidate") if json_str_candidate else (text, "full text response")
    cleaned_json_str = _clean_json_string(text_to_parse)
    try:
        return json.loads(cleaned_json_str)
    except json.JSONDecodeError as json_err:
        try:
            pythonic_str = cleaned_json_str.replace('true', 'True').replace('false', 'False').replace('null', 'None')
            return ast.literal_eval(pythonic_str)
        except (ValueError, SyntaxError, MemoryError, TypeError, RecursionError) as ast_err:
            raise JSONParsingError(f"Failed to parse {source_label} as JSON or Python literal.", text=cleaned_json_str, original_exception=ast_err) from ast_err
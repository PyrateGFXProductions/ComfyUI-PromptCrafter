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
    if not text:
        return None
        
    # First, try to find a JSON block within markdown code fences
    # We look for the FIRST one that looks like JSON
    match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\}|\[[\s\S]*?\])\s*```", text, re.DOTALL)
    if match:
        return match.group(1)

    # If no markdown block is found, find the first opening brace or bracket
    first_brace = text.find('{')
    first_bracket = text.find('[')

    # Determine the starting position of the JSON
    start_pos = -1
    if first_brace != -1 and first_bracket != -1:
        start_pos = min(first_brace, first_bracket)
    elif first_brace != -1:
        start_pos = first_brace
    elif first_bracket != -1:
        start_pos = first_bracket
    
    if start_pos == -1:
        return None

    start_char = text[start_pos]
    end_char = '}' if start_char == '{' else ']'

    balance, in_string, is_escaped = 1, False, False
    for i in range(start_pos + 1, len(text)):
        char = text[i]
        
        if char == '"' and not is_escaped:
            in_string = not in_string
        
        if not in_string:
            if char == start_char: balance += 1
            elif char == end_char: balance -= 1
        
        if balance == 0:
            return text[start_pos : i + 1]
            
        is_escaped = (char == "\\" and not is_escaped)
        
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
    # Remove markdown code fences if they somehow got in
    cleaned_str = re.sub(r"```(?:json)?", "", json_str)
    cleaned_str = re.sub(r"```", "", cleaned_str)
    
    # Remove common LLM-specific garbage
    cleaned_str = re.sub(r'</?ref>', '', cleaned_str)
    cleaned_str = re.sub(r"^\s*//.*$", "", cleaned_str, flags=re.MULTILINE)
    cleaned_str = re.sub(r'/\*[\s\S]*?\*/', '', cleaned_str)
    
    # Handle unquoted keys (e.g., {key: "value"} -> {"key": "value"})
    cleaned_str = re.sub(r"([{,]\s*)([a-zA-Z0-9_.-]+)(\s*:)", r'\1"\2"\3', cleaned_str)
    
    # Handle single-quoted keys and values
    cleaned_str = re.sub(r"([{\,]\s*)'([^']*)'(\s*:)", r'\1"\2"\3', cleaned_str)
    cleaned_str = re.sub(r'(:\s*)\'([^\']*)\'', r'\1"\2"', cleaned_str)
    
    # Remove trailing commas in objects and arrays
    cleaned_str = re.sub(r",\s*([}\]])", r"\1", cleaned_str)
    
    # Standardize booleans and nulls
    cleaned_str = re.sub(r'\bTrue\b', 'true', cleaned_str, flags=re.IGNORECASE)
    cleaned_str = re.sub(r'\bFalse\b', 'false', cleaned_str, flags=re.IGNORECASE)
    cleaned_str = re.sub(r'\bNone\b', 'null', cleaned_str, flags=re.IGNORECASE)
    
    return "".join(_escape_newlines_in_strings(cleaned_str)).strip()

def extract_and_parse_json(text: str):
    """
    Extracts and parses a JSON object from a string that may contain other text.
    Handles common LLM formatting errors and provides Pythonic literal fallback.
    """
    if not text or not text.strip(): 
        return None
        
    json_str_candidate = _find_json_candidate(text)
    if not json_str_candidate:
        return None
        
    cleaned_json_str = _clean_json_string(json_str_candidate)
    
    try:
        return json.loads(cleaned_json_str)
    except json.JSONDecodeError:
        # Fallback to Python literal evaluation if JSON fails
        try:
            pythonic_str = (cleaned_json_str
                .replace('true', 'True')
                .replace('false', 'False')
                .replace('null', 'None'))
            return ast.literal_eval(pythonic_str)
        except Exception:
            # If everything fails, return None or raise specific error
            return None

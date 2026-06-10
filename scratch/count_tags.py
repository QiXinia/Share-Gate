def count_tags():
    with open("static/index.html", "r", encoding="utf-8") as f:
        content = f.read()
    
    # We can do a simple parse of div, main, aside, body tags
    import re
    # Find all tags
    tags = re.findall(r'</?(?:div|aside|main|body|header|footer)\b', content)
    
    stack = []
    errors = []
    
    for tag in re.finditer(r'<(/)?(div|aside|main|body|header|footer)\b', content):
        is_closing = tag.group(1) is not None
        tag_name = tag.group(2)
        line_num = content.count('\n', 0, tag.start()) + 1
        
        if not is_closing:
            stack.append((tag_name, line_num))
        else:
            if not stack:
                errors.append(f"Unmatched closing tag </{tag_name}> at line {line_num}")
            else:
                top_name, top_line = stack.pop()
                if top_name != tag_name:
                    errors.append(f"Mismatched closing tag </{tag_name}> at line {line_num} (expected </{top_name}> opened at line {top_line})")
                    # Push back the mismatch to try and recover
                    stack.append((top_name, top_line))
                    
    while stack:
        top_name, top_line = stack.pop()
        errors.append(f"Unclosed tag <{top_name}> opened at line {top_line}")
        
    for err in errors:
        print(err)

if __name__ == "__main__":
    count_tags()

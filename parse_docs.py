import re

def parse_markdown_for_opcode_map(file_path):

    with open(file_path, 'r') as f:
        md_content = f.read()

    opcode_map = {}
    current_opcode = None
    current_function = None
    current_req = None
    current_rsp = None

    # Normalize newlines
    lines = md_content.splitlines()
    for i, line in enumerate(lines):
        # Match headers like ## Identify (0001h)
        m = re.match(r'## .+\((\w{4})h\)', line)
        if m:
            current_opcode = m.group(1).lower()
            current_function = None
            current_req = None
            current_rsp = None
            continue

        # Match C function signature and extract function name and param types
        if line.strip().startswith("int cxlmi_cmd"):
            func_line = line.strip().strip('`').strip(';')
            func_match = re.match(r'int (\w+)\s*\(.*', func_line)
            if func_match:
                current_function = func_match.group(1)

                # Check next few lines for *in or *ret to determine req/rsp
                for offset in range(0, 10):
                    if i + offset >= len(lines):
                        break
                    l = lines[i + offset]
                    struct_match = re.search(r'struct\s+(\w+)\s*\*\s*(in|ret)', l)
                    if struct_match:
                        struct_name = struct_match.group(1)
                        direction = struct_match.group(2)
                        if direction == 'in':
                            current_req = f'struct {struct_name}'
                        elif direction == 'ret':
                            current_rsp = f'struct {struct_name}'

                if current_opcode:
                    opcode_map[current_opcode] = {
                        'function': current_function,
                        'req': current_req,
                        'rsp': current_rsp
                    }

    return opcode_map

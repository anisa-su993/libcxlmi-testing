import xml.etree.ElementTree as ET
import subprocess
import shlex
import argparse
from parse_docs import parse_markdown_for_opcode_map

PREFIX = """#include <stdio.h>
#include <stdlib.h>
#include <assert.h>
#include <libcxlmi.h>

#define MAX_PAYLOAD_SIZE 4096
"""

ASSERT_MACRO = """
#define ASSERT_EQUAL(expected, actual, field) \\
    if ((expected).field != (actual)->field) { \\
        printf("Assertion failed: %s.%s = %llu, %s->%s = %llu\\n", \\
               #expected, #field, (expected).field, \\
               #actual, #field, (actual)->field); \\
        rc = EXIT_FAILURE; \\
    }
"""

ASSERT_MACRO_FATAL = """
#define ASSERT_EQUAL_FATAL(expected, actual, field) \\
    if ((expected).field != (actual)->field) { \\
        printf("Assertion failed: %s.%s = %llu, %s->%s = %llu\\n", \\
               #expected, #field, (expected).field, \\
               #actual, #field, (actual)->field); \\
        rc = EXIT_FAILURE; \\
        goto cleanup; \\
    }
"""

MAIN = """
int main() {
    struct cxlmi_ctx *ctx;
    struct cxlmi_endpoint *ep, *tmp;
    void *buf = calloc(1, MAX_PAYLOAD_SIZE);
    int rc = EXIT_FAILURE;

    assert(buf != NULL);
    ctx = cxlmi_new_ctx(stderr, DEFAULT_LOGLEVEL);
    assert(ctx != NULL);
"""

MCTP = """
    printf("scanning dbus...\\n");

    int num_ep = cxlmi_scan_mctp(ctx);
    if (num_ep < 0) {
        fprintf(stderr, "dbus scan error\\n");
        goto exit_free_ctx;
    } else if (num_ep == 0) {
        printf("no endpoints found\\n");
    } else {
        printf("found %d endpoint(s)\\n", num_ep);
    }

    cxlmi_for_each_endpoint_safe(ctx, ep, tmp) {
"""

DEVNAME = ""

IOCTL = f"""
    ep = cxlmi_open(ctx, {DEVNAME});
	if (!ep) {{
		fprintf(stderr, "cannot open '%s' endpoint\\n", {DEVNAME});
		goto exit_free_ctx;
    }}
"""

FOOTER = """
        cxlmi_close(ep);
    }

cleanup:
    cxlmi_for_each_endpoint_safe(ctx, ep, tmp) {
        cxlmi_close(ep);
    }
exit_free_ctx:
    free(buf);
    cxlmi_free_ctx(ctx);
    return rc;
}
"""

G_COUNT = 1
G_INDENT_LEVEL = 2
ASSERT_INDENT = "    " * G_INDENT_LEVEL
ASSERT_TYPE = "ASSERT_EQUAL"
TUNNEL_INFO = "NULL"

def get_expected_str():
    return 'expected_' + str(G_COUNT)

def get_actual_str():
    return 'actual_' + str(G_COUNT)

def get_req_str():
    return 'request_' + str(G_COUNT)

def generate_struct_body(element, indent_level=0, expected_name="expected_rsp", actual_name="actual"):
    indent = "    " * indent_level
    struct_body = "{\n"
    assertions = ""

    for child in element:
        field_name = child.tag
        child_elements = list(child)

        # Case: Array of structs
        if len(child_elements) > 1 and all(e.tag == child_elements[0].tag for e in child_elements):
            struct_body += f"{indent}    .{field_name} = {{\n"
            for i, entry in enumerate(child_elements):
                nested_body, nested_assertions = generate_struct_body(
                    entry,
                    indent_level + 2,
                    f"{expected_name}.{field_name}[{i}]",
                    f"&{actual_name}->{field_name}[{i}]"
                )
                struct_body += f"{indent}        {nested_body},\n"
                assertions += nested_assertions
            struct_body += f"{indent}    }},\n"

        # Case: Nested struct
        elif len(child_elements) > 0:
            nested_body, nested_assertions = generate_struct_body(
                child,
                indent_level + 1,
                f"{expected_name}.{field_name}",
                f"{actual_name}->{field_name}"
            )
            struct_body += f"{indent}    .{field_name} = {nested_body},\n"
            assertions += nested_assertions

        # Case: Scalar field
        else:
            struct_body += f"{indent}    .{field_name} = {child.text},\n"
            assertions += f"{ASSERT_INDENT}{ASSERT_TYPE}({expected_name}, {actual_name}, {field_name});\n"

    struct_body += f"{indent}}}"
    return struct_body, assertions


def generate_struct_code(var_name, struct_name, element, indent_level=0):
    """
    Recursively generate C code for requests/expected responses from the
    given XML node.

    Parameters:
        - var_name: variable name for the request/response
        (ex: req_1/expected_1/actual_1, etc.)
        - struct_name: name of the struct (ex: cxlmi_cmd_XXX_req/cxlmi_cmd_XXX_rsp)
        - element: corresponding XML node
        - indent_level: indent level

    Requests are generated in the following format. :
        struct cxlmi_cmd_XXX_req expected_1 = {
            .field_1 = value_1,
            .field_2 = value_2,
            ...
        }
    where value_1 and value_2 are read from the XML node.

    Expected responses are generated similarly with their assertions:
     struct cxlmi_cmd_XXX_rsp actual_1 = {
        .field_1 = value_1,
        ...
     }

     ASSERT_EQUAL(expected_1, actual_1, field_1);

     OR if the response node is empty, return ""
    """
    if len(element) == 0:
        return "", ""

    struct_body, assertions = generate_struct_body(element,
                                                   indent_level,
                                                   expected_name=get_expected_str(),
                                                   actual_name=get_actual_str())
    indent = "    " * indent_level
    code = f"{indent}{struct_name} {var_name} = {struct_body};\n\n"
    return code, assertions

# Generate code for the main test logic
def generate_c_code(command, opcode_map):
    opcode = command.attrib['opcode']
    if opcode not in opcode_map:
        return f"// Unknown opcode {opcode}\n"

    mapping = opcode_map[opcode]
    func = mapping['function']
    request = command.find("request")
    response = command.find("response")

    req_str = get_req_str()
    actual = get_actual_str()
    expected = get_expected_str()

    req_code, expected_rsp_code, assertions = "", "", ""

    if request is not None:
        req_struct = mapping['req']
        # Generate req struct initialization
        req_code, _ = generate_struct_code(req_str,
                                           req_struct,
                                           request,
                                           indent_level=G_INDENT_LEVEL)

    if response is not None:
        rsp_struct = mapping['rsp']
        # Generate expected rsp struct initialization and checks
        expected_rsp_code, assertions = generate_struct_code(expected,
                                                         rsp_struct,
                                                         response,
                                                         indent_level=G_INDENT_LEVEL)

    function_call = ""
    cast_rsp = ""

    if response is not None:
        cast_rsp = f"{rsp_struct} *{actual} = ({rsp_struct} *) buf;"
        if request is not None:
            function_call = f"{func}(ep, {TUNNEL_INFO}, &{req_str}, {actual})"
        else:
            function_call = f"{func}(ep, {TUNNEL_INFO}, {actual})"
    elif request is not None:
        function_call = f"{func}(ep, {TUNNEL_INFO}, &{req_str})"
    else:
        function_call = f"{func}(ep, {TUNNEL_INFO})"

    # Allocate and call the function
    alloc_and_call = f"""\
        {cast_rsp}

        rc = {function_call};
        if (rc != 0) {{
            fprintf(stderr, "Error: Function {func} returned non-zero rc: %d\\n", rc);
            goto cleanup;
        }}
"""

    return req_code + expected_rsp_code + alloc_and_call + assertions + "\n"

def load_xml_from_file(file_path):
    tree = ET.parse(file_path)
    return tree.getroot()

def generate_test_file(filename, root):
    # Step 1: Open in write mode to clear the file
    with open(filename, 'w') as f:
        pass

    # Step 2: Open in append mode to add the content
    with open(filename, 'a', newline='') as f:
        # Write the prefix (C file header) to the file
        f.write(PREFIX + "\n")

        # Write the generated assert macro to the file with explicit newlines
        f.write(ASSERT_MACRO)
        f.write(ASSERT_MACRO_FATAL)

        f.write(MAIN)
        f.write(MCTP)

        # Generate and write the C code for each command
        for command in root.findall('command'):
            f.write(generate_c_code(command, opcode_map))
            global G_COUNT
            G_COUNT += 1

        # Write the footer to the file
        f.write(FOOTER)

def run_command(command):
    print(f"Running command: {command}")
    argv = shlex.split(command)

    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=5)

        print("STDOUT:")
        print(result.stdout)
        print("STDERR:")
        print(result.stderr)
    except:
        print("Error")

def add_args(parser):
    parser.add_argument('input', type=str, nargs='?',
                        default="commands.xml",
                        help='Path to the XML file containing commands')
    parser.add_argument('-o', '--output', type=str, required=False,
                        default="output.c",
                        help='Output C file name')
    parser.add_argument('-f', '--fatal', action='store_true', required=False,
                        help='Stop execution on assertion failure')

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    add_args(parser)
    args = parser.parse_args()

    opcode_map = {}
    opcode_map = parse_markdown_for_opcode_map("./libcxlmi/docs/Generic-Component-Commands.md")
    opcode_map.update(parse_markdown_for_opcode_map("./libcxlmi/docs/Memory-Device-Commands.md"))
    opcode_map.update(parse_markdown_for_opcode_map("./libcxlmi/docs/FM-API.md"))

    # Dump opcode map to a file
    with open('opcode_map.txt', 'w') as f:
        for opcode, info in opcode_map.items():
            f.write(f"Opcode: {opcode}\n")
            for key, value in info.items():
                f.write(f"  {key}: {value}\n")
            f.write("\n")
    print("Opcode Info dumped to opcode_map.txt")

    input_file = args.input
    output_file = args.output
    root = load_xml_from_file(input_file)

    if args.fatal:
        ASSERT_TYPE = "ASSERT_EQUAL_FATAL"

    generate_test_file(output_file, root)

    print(f"Code has been written to {output_file}")

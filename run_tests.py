import sys
import os
import shutil
import argparse
import xml.etree.ElementTree as ET
from topo import SUITES
from parse_docs import generate_default_opcode_map, print_opcode_map
from generate_tests import generate_test_file, load_xml

# Add cxl_test_tool to the module search path to import necessary packages
subdir_path = os.path.join(os.path.dirname(__file__), 'cxl_test_tool')
sys.path.insert(0, subdir_path)
from cxl_test_tool.utils import tools, mctp, cxl, config

opcode_map = {}

# GH Runner clones libcxlmi on PR. Copy from runner to VM
def install_libcxlmi(target_dir="./libcxlmi"):
    tools.copy_to_remote(src=".", dst=".")

    tools.install_packages_on_vm("meson libdbus-1-dev git cmake locales")
    cmd="git clone -b %s --single-branch %s %s"%(branch, url, target_dir)
    tools.execute_on_vm(cmd, echo=True)
    cmd="cd %s; meson setup -Dlibdbus=enabled build; meson compile -C build;"%target_dir
    tools.execute_on_vm(cmd, echo=True)

    if tools.path_exist_on_vm(target_dir):
        print("INFO: Install libcxlmi succeeded")
        return 0

    print("ERROR: Install libcxlmi failed!")
    return -1

def start_vm(suite, output_file):
    # Start VM, set up MCTP (if applicable), load drivers, and clone libcxlmi
    tools.run_qemu(topo=suite["qemu_str"], kernel=KERNEL_IMG, qemu=QEMU_IMG)
    print('-------------------------------------------------')
    if suite["mctp"] is not None:
        mctp.mctp_setup(CXL_TEST_TOOL_DIR + "/test-workflows/mctp.sh")
        print('-------------------------------------------------')

    cxl.load_driver()
    print('-------------------------------------------------')
    install_libcxlmi(target_dir='./libcxlmi')
    print('-------------------------------------------------')
    tools.execute_on_vm('cxl list', echo=True)
    print('-------------------------------------------------')

    # Copy test file to VM and compile
    libcxlmi_incl = './libcxlmi/src'
    libcxlmi_bin = './libcxlmi/build/src'
    compile_str = f'gcc /tmp/{output_file} -I{libcxlmi_incl} -L{libcxlmi_bin} -lcxlmi -o /tmp/{output_file[:-2]}'
    tools.copy_to_remote(output_file, dst=f"/tmp/{output_file}")
    print('-------------------------------------------------')
    print(tools.execute_on_vm(compile_str, echo=True))
    print('-------------------------------------------------')

def execute_test(opcode, output_file):
    # Execute tests and capture output
    results_file = f"./output/{output_file[:-2]}-results.txt"
    with open(results_file, 'w') as f:
        results = tools.execute_on_vm(f'/tmp/{output_file[:-2]}', echo=False)
        f.write(results)
        if results.splitlines()[:-1] == "All tests passed":
            print(f"Test {opcode} passed.")
        else:
            print(f"Test {opcode} failed. Check {results_file} for details.")

def run_test(opcode):
    suite = opcode_map[opcode]['suite']
    print(f"Opcode {opcode} belongs to suite {suite}")

    suite_info = SUITES[suite]
    input_file = suite_info['input']
    test_file = 'test-' + opcode + '.c'
    results_file = test_file[:-2] + '-results.txt'

    root = load_xml(input_file)
    command_xml = next((child for child in root if child.attrib.get('opcode') == opcode), None)
    print(ET.tostring(command_xml).decode())

    generate_test_file(test_file, command_xml, suite_info, opcode_map)
    print(f"Code has been written to ./output/{test_file}")

    start_vm(suite_info, test_file)
    execute_test(opcode, results_file)

    # Shut down VM and clean up
    print('Shutting down VM...')
    tools.execute_on_vm('rm -rf libcxlmi')
    tools.shutdown_vm()


def run_suite(suite):
    # Generate C test code
    input_file = suite['input']
    output_file = 'test-' + suite.lower().replace('_', '-') + '.c'
    root = load_xml(input_file)

    generate_test_file(output_file, root, suite, opcode_map)

    print(f"Code has been written to {output_file}")

    # Start VM, set up MCTP (if applicable), load drivers, and clone libcxlmi
    tools.run_qemu(topo=suite["qemu_str"], kernel=KERNEL_IMG, qemu=QEMU_IMG)
    print('-------------------------------------------------')
    if suite["mctp"] is not None:
        mctp.mctp_setup(CXL_TEST_TOOL_DIR + "/test-workflows/mctp.sh")
        print('-------------------------------------------------')

    cxl.load_driver()
    print('-------------------------------------------------')
    install_libcxlmi(target_dir='./libcxlmi')
    print('-------------------------------------------------')
    tools.execute_on_vm('cxl list', echo=True)
    print('-------------------------------------------------')

    # Copy test file to VM and compile
    libcxlmi_incl = './libcxlmi/src'
    libcxlmi_bin = './libcxlmi/build/src'
    compile_str = f'gcc /tmp/{output_file} -I{libcxlmi_incl} -L{libcxlmi_bin} -lcxlmi -o /tmp/{output_file[:-2]}'
    tools.copy_to_remote(output_file, dst=f"/tmp/{output_file}")
    print('-------------------------------------------------')
    print(tools.execute_on_vm(compile_str, echo=True))
    print('-------------------------------------------------')

    # Execute tests and capture output
    results_file = f"./{output_file[:-2]}-results.txt"
    with open(results_file, 'w') as f:
        f.write(f"Test results for {topo}:\n")
        f.write("------------------------------------\n")
        results = tools.execute_on_vm(f'/tmp/{output_file[:-2]}', echo=False)
        f.write(results)
        if results.splitlines()[:-1] == "All tests passed":
            print("All tests passed successfully.\n")
        else:
            print("Some tests failed. Check the output for details.\n")
            print('Results for %s written to %s' % (topo, f.name))

    # Shut down VM and clean up
    print('Shutting down VM...')
    tools.execute_on_vm('rm -rf libcxlmi')
    tools.shutdown_vm()


def run_all():
    for suite, topo_info in SUITES.items():
        # Generate C test code
        input_file = topo_info['input']
        output_file = 'test-' + topo.lower().replace('_', '-') + '.c'
        root = load_xml(input_file)

        generate_test_file(output_file, root, topo_info)
        if topo_info["mctp"] and not args.ioctl:
            generate_test_file(output_file, root, topo_info)
        else:
            devname = topo_info['ioctl']
            generate_test_file(output_file, root, t)
        print(f"Code has been written to {output_file}")

        # Start VM, set up MCTP (if applicable), load drivers, and clone libcxlmi
        tools.run_qemu(topo=topo_info["topo_str"], kernel=KERNEL_IMG, qemu=QEMU_IMG)
        print('-------------------------------------------------')
        if topo_info["has_mctp"]:
            mctp.mctp_setup(CXL_TEST_TOOL_DIR + "/test-workflows/mctp.sh")
            print('-------------------------------------------------')
        cxl.load_driver()
        print('-------------------------------------------------')
        install_libcxlmi(target_dir='./libcxlmi')
        print('-------------------------------------------------')
        tools.execute_on_vm('cxl list', echo=True)
        print('-------------------------------------------------')

        # Copy test file to VM and compile
        libcxlmi_incl = './libcxlmi/src'
        libcxlmi_bin = './libcxlmi/build/src'
        compile_str = f'gcc /tmp/{output_file} -I{libcxlmi_incl} -L{libcxlmi_bin} -lcxlmi -o /tmp/{output_file[:-2]}'
        tools.copy_to_remote(output_file, dst=f"/tmp/{output_file}")
        print('-------------------------------------------------')
        print(tools.execute_on_vm(compile_str, echo=True))
        print('-------------------------------------------------')

        # Execute tests and capture output
        results_file = f"./{output_file[:-2]}-results.txt"
        with open(results_file, 'w') as f:
            f.write(f"Test results for {topo}:\n")
            f.write("------------------------------------\n")
            results = tools.execute_on_vm(f'/tmp/{output_file[:-2]}', echo=False)
            f.write(results)
            if results.splitlines()[:-1] == "All tests passed":
                print("All tests passed successfully.\n")
            else:
                print("Some tests failed. Check the output for details.\n")
            print('Results for %s written to %s' % (topo, f.name))

        # Shut down VM and clean up
        print('Shutting down VM...')
        tools.execute_on_vm('rm -rf libcxlmi')
        tools.shutdown_vm()


def clear_subdir(path):
    for filename in os.listdir(path):
        full_path = os.path.join(path, filename)
        try:
            if os.path.isfile(full_path) or os.path.islink(full_path):
                os.unlink(full_path)  # remove file or symlink
            elif os.path.isdir(full_path):
                shutil.rmtree(full_path)  # remove directory recursively
        except Exception as e:
            print(f'Failed to delete {full_path}. Reason: {e}')

def add_args(parser):
    parser.add_argument('-t', '--test', type=str, required=False, help='opcode of the test')
    parser.add_argument('-s', '--suite', type=str, required=False, help='test suite (defined in topo.py)')

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    add_args(parser)
    args = parser.parse_args()

    # Set up cxl-test-tool
    config.parse_config('./.vars.config')

    # Clear output dir from prev. run
    clear_subdir('./output')

    # Parse opcode map
    opcode_map = generate_default_opcode_map()
    print_opcode_map(opcode_map)

    QEMU_IMG=tools.system_path("QEMU_IMG")
    KERNEL_IMG=tools.system_path("KERNEL_IMG")
    CXL_TEST_TOOL_DIR=tools.system_path("cxl_test_tool_dir")

    if args.test:
        run_test(args.test)
    elif args.suite:
        run_suite(args.suite)
    else:
        run_all()
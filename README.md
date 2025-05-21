# libcxlmi-testing
Tests [libcxlmi](https://github.com/computexpresslink/libcxlmi) using QEMU.
Kernel and QEMU versions configurable via .vars.config

Current QEMU branch used to test: https://github.com/anisa-su993/qemu-anisa/tree/fmapi-dcd-v2

Linux version: https://github.com/anisa-su993/anisa-linux-kernel/tree/mctp-hack

Credits: Yanks utils directory from [cxl-test-tool](https://github.com/moking/cxl-test-tool)

## Table of Contents
- [Goals](#goals)
- [How It Works](#installation)
- [Usage](#usage)
- [License](#license)

## Goals
The goal of end-to-end tests with QEMU is to ensure that the library is able to properly interact with the device, which includes all the layers between calling the cxlmi_cmd_X() function to interpreting and returning the end result from the device. As an example of what gets called from a cxlmi_cmd_X() call:

cxlmi_cmd_identify() → send_cmd_cci() → send_mctp_direct() → sanity_check_mctp_rsp()

This example shows the call stack for a direct MCTP message, but it will be different for an ioctl endpoint and/or with tunneling.

The best way to test this sequence of interactions will be with QEMU.

## How it Works
generate_tests.py reads an XML file where the command input/expected outputs are defined and generates C test code based on that.

### Input
Define commands you want to test in XML file. Some commands don't have any input/output, some have one or the other, or both:

```
# This command has both an input and output
int cxlmi_cmd_fmapi_dc_list_tags(struct cxlmi_endpoint *ep,
			struct cxlmi_tunnel_info *ti,
			struct cxlmi_cmd_fmapi_dc_list_tags_req *in,
			struct cxlmi_cmd_fmapi_dc_list_tags_rsp *ret);

# This command only has an output and no input
int cxlmi_cmd_fmapi_identify_sw_device(struct cxlmi_endpoint *ep,
		       struct cxlmi_tunnel_info *ti,
		       struct cxlmi_cmd_fmapi_identify_sw_device *ret);

# This command only has an input and no output
int cxlmi_cmd_memdev_release_dc(struct cxlmi_endpoint *ep,
				struct cxlmi_tunnel_info *ti,
				struct cxlmi_cmd_memdev_release_dc *in);

# This command has no input or output
int cxlmi_cmd_request_bg_op_abort(struct cxlmi_endpoint *ep,
				  struct cxlmi_tunnel_info *ti);
```

Commands must be defined correctly in the input file or behavior is undefined
(most likely the test code will not compile).
Ex: defining an input when none is expected, including an incorrect field in
the req/rsp

Below is an example of the definition of a command with both input and output:
```
<command opcode="0004">
    <request>
        <limit>10</limit>
    </request>
    <response>
        <limit>10</limit>
    </response>
</command>
```
This corresponds to the following libcxlmi command with the corresponding request/response struct(s):
```
int cxlmi_cmd_set_response_msg_limit(struct cxlmi_endpoint *ep,
			     struct cxlmi_tunnel_info *ti,
			     struct cxlmi_cmd_set_response_msg_limit *in,
			     struct cxlmi_cmd_set_response_msg_limit *ret);

/* CXL r3.1 Section 8.2.9.1.4: Set Response Message Limit (Opcode 0004h) */
struct cxlmi_cmd_set_response_msg_limit {
	uint8_t limit;
} __attribute__((packed));
```
The above XML will generate the following code:

```
struct cxlmi_cmd_set_response_msg_limit *actual = (struct cxlmi_cmd_set_response_msg_limit *) buf;

rc = cxlmi_cmd_set_response_msg_limit(ep, NULL, &request, actual);
if (rc != 0) {
    fprintf(stderr, "Error: Function cxlmi_cmd_set_response_msg_limit returned  non-zero rc: %d\n", rc);
    goto cleanup;
}
ASSERT_EQUAL(expected, actual, limit);
```
Note that the output defined in the XML file is the *expected output*. Defining the expected output is *optional*. If none is defined, the generated code will only check the rc. For example:

```
<command opcode="0004">
    <request>
        <limit>10</limit>
    </request>
    <response>
        <!-- empty -->
    </response>
</command>
```
Notice that the `<response>` node is still required. The `<response>` node *must*
bt included for every command that expects a response. Filling out the fields is
optional and the response node can be empty.
This will generate the following test code, skipping the assertions:
```
struct cxlmi_cmd_set_response_msg_limit *actual = (struct cxlmi_cmd_set_response_msg_limit *) buf;

rc = cxlmi_cmd_set_response_msg_limit(ep, NULL, &request, actual);
if (rc != 0) {
    fprintf(stderr, "Error: Function cxlmi_cmd_set_response_msg_limit returned  non-zero rc: %d\n", rc);
    goto cleanup;
}
```

### VM Start-Up
Topologies are defined in topo.py
The script will automatically start a VM with each topology:
- clone libcxlmi on the VM
- copy generated test-code.c file on the VM
- compile and run the test code on the VM
- collect and write the results to a file
- shut down the VM
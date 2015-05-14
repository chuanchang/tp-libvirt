import os
import logging
from virttest import utils_v2v
from virttest import utils_misc
from autotest.client import utils
from autotest.client.shared import ssh_key, error


def get_args_dict(params):
    args_dict = {}
    keys_list = ['target', 'main_vm', 'ovirt_engine_url', 'ovirt_engine_user',
                 'ovirt_engine_password', 'hypervisor', 'storage', 'username']

    if params.get('network'):
        keys_list.append('network')

    if params.get('bridge'):
        keys_list.append('bridge')

    hypervisor = params.get('hypervisor')
    if hypervisor == 'esx':
        esx_args_list = ['vpx_ip', 'vpx_pwd', 'vpx_pwd_file',
                         'vpx_dc', 'esx_ip', 'v2v_opts', 'hostname']
        keys_list += esx_args_list

    if hypervisor == 'xen':
        xen_args_list = ['xen_ip', 'xen_pwd', 'hostname']
        keys_list += xen_args_list

    for key in keys_list:
        val = params.get(key)
        if val is None:
            raise KeyError("%s doesn't exist!!!" % key)
        elif val.count("EXAMPLE"):
            raise error.TestNAError("Please provide specific value for %s: %s",
                                    key, val)
        else:
            args_dict[key] = val

    logging.debug(args_dict)
    return args_dict


def run(test, params, env):
    """
    Test convert vm to ovirt
    """

    args_dict = get_args_dict(params)
    hypervisor = args_dict.get('hypervisor')
    xen_ip = args_dict.get('xen_ip')
    xen_pwd = args_dict.get('xen_pwd')
    username = args_dict.get('username', 'root')
    vpx_pwd = args_dict.get('vpx_pwd')
    vpx_pwd_file = args_dict.get('vpx_pwd_file')

    # Set libguestfs environment
    os.environ['LIBGUESTFS_BACKEND'] = 'direct'

    if hypervisor == 'xen':
        ssh_key.setup_ssh_key(xen_ip, user=username,
                              port=22, password=xen_pwd)
        # Note that password-interactive and Kerberos access are not supported.
        # You have to set up ssh access using ssh-agent and authorized_keys.
        try:
            utils_misc.add_identities_into_ssh_agent()
        except:
            utils.run("ssh-agent -k")
            raise error.TestFail("Failed to start 'ssh-agent'")

    if hypervisor == 'esx':
        logging.info("Building ESX no password interactive verification.")
        fp = open(vpx_pwd_file, 'w')
        fp.write(vpx_pwd)
        fp.close()

    try:
        # Run test case
        utils_v2v.v2v_cmd(args_dict)
    finally:
        if hypervisor == "xen":
            utils.run("ssh-agent -k")

        if hypervisor == "esx":
            utils.run("rm -rf %s" % vpx_pwd_file)

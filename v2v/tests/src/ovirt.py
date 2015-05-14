import logging
from virttest import ovirt
from autotest.client.shared import error


def get_args_dict(params):
    args_dict = {}
    keys_list = ['ovirt_engine_url', 'ovirt_engine_user',
                 'ovirt_engine_password', 'main_vm', 'export_name',
                 'storage_name', 'cluster_name']

    for key in keys_list:
        val = params.get(key)
        if val is None:
            raise KeyError("%s doesn't exist!!!" % key)
        else:
            args_dict[key] = val

    return args_dict


def run(test, params, env):
    """
    Test ovirt class
    """

    args_dict = get_args_dict(params)
    logging.debug("arguments dictionary: %s" % args_dict)

    vm_name = params.get('main_vm')
    export_name = params.get('export_name')
    storage_name = params.get('storage_name')
    cluster_name = params.get('cluster_name')
    address_cache = env.get('address_cache')

    # Run test case
    vm = ovirt.VMManager(params, address_cache)
    dc = ovirt.DataCenterManager(params)
    cls = ovirt.ClusterManager(params)
    ht = ovirt.HostManager(params)
    sd = ovirt.StorageDomainManager(params)

    logging.info("Current data centers list: %s" % dc.list())
    logging.info("Current cluster list: %s" % cls.list())
    logging.info("Current host list: %s" % ht.list())
    logging.info("Current storage domain list: %s" % sd.list())
    logging.info("Current vm list: %s" % vm.list())

    vm.import_from_export_domain(export_name, storage_name, cluster_name)
    vm_list = vm.list()
    logging.debug("The latest list: %s" % vm_list)
    if vm_name not in vm_list:
        raise error.TestFail("Faild to import '%s' to '%s'", vm_name, storage_name)    

    vm.start()

    if not vm.is_alive():
        raise error.TestFail("The '%s' isn't running", vm_name)    

    logging.info("The %s is alive" % vm_name)
    
#    vm.suspend()
#    vm.resume()
#    vm.shutdown()

#    if not vm.is_dead():
#        raise error.TestFail("The '%s' is still running", vm_name)    

#    logging.info("The %s is dead" % vm_name)

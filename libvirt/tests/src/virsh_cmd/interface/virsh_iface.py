import os
import logging
from autotest.client import utils
from autotest.client.shared import error
from virttest.utils_test import libvirt
from virttest.staging import service
from virttest import utils_net
from virttest import utils_misc
from virttest import virsh
from virttest import remote
from virttest.libvirt_xml import vm_xml

NETWORK_SCRIPT = "/etc/sysconfig/network-scripts/ifcfg-"


def create_xml_file(xml_file, params):
    """
    Create a xml file contained interface definition
    """
    iface_type = params.get("iface_type")
    iface_name = params.get("iface_name")
    iface_eth = params.get("iface_eth")
    iface_pro = params.get("iface_pro")
    iface_ip = params.get("ping_ip")
    iface_stp = params.get("iface_stp")
    iface_tag = params.get("iface_tag")
    if iface_type == "vlan":
        iface_name = iface_eth + "." + iface_tag
    xml_info = """
<interface type='%s' name='%s'>""" % (iface_type, iface_name)

    if iface_type in ["bridge", "ethernet"]:
        xml_info += """
  <start mode='onboot'/>"""

        # bridge protocol part
        if iface_pro == "dhcp":
            xml_info += """
   <protocol family='ipv4'>
     <%s/>
   </protocol>""" % iface_pro
        elif iface_pro == "static":
            xml_info += """
   <protocol family='ipv4'>
     <ip address='%s' prefix='24'/>
   </protocol>""" % iface_ip

        # bridge stp part
        if not iface_stp:
            xml_info += """
   <bridge>"""
        elif iface_stp == "yes":
            xml_info += """
   <bridge stp="on" delay="0">"""
        elif iface_stp == "no":
            xml_info += """
   <bridge stp="off" delay="0">"""

        # bridge tail part
        xml_info += """
   </bridge>
</interface>"""

    elif iface_type == "vlan":
        xml_info += """
  <start mode='none'/>
   <protocol family='ipv4'>
     <ip address='%s'/>
   </protocol>
   <vlan tag='%s'>
     <interface name='%s'/>
   </vlan>
</interface>""" % (iface_ip, iface_tag, iface_eth)

    elif iface_type == "bond":
        xml_info += """
  <start mode='none'/>"""
        if iface_ip:
            xml_info += """
   <protocol family='ipv4'>
     <ip address='%s'/>
   </protocol>
   <bond>
     <interface type='ethernet' name='%s'>
     </interface>
   </bond>
</interface>""" % (iface_ip, iface_eth)
        else:
            xml_info += """
   <bond>
   </bond>
</interface>"""
    iface_file = open(xml_file, 'w')
    iface_file.write(xml_info)
    iface_file.close()


def run(test, params, env):
    """
    Test virsh interface related commands.

    (1) If using given exist interface for testing(eg. lo or ethX):
        1.1 Dumpxml for the interface(with --inactive option)
        1.2 Destroy the interface
        1.3 Undefine the interface
    (2) Define an interface from XML file
    (3) List interfaces with '--inactive' optioin
    (4) Start the interface
    (5) List interfaces with no option
    (6) Dumpxml for the interface
    (7) Get interface MAC address by interface name
    (8) Get interface name by interface MAC address
    (9) Delete interface if not use the exist interface for testing
        9.1 Destroy the interface
        9.2 Undefine the interface

    Caveat, this test may affect the host network, so using the loopback(lo)
    device by default. You can specify the interface which you want, but be
    careful.
    """

    iface_name = params.get("iface_name")
    iface_xml = params.get("iface_xml")
    iface_type = params.get("iface_type", "ethernet")
    iface_pro = params.get("iface_pro", "")
    iface_eth = params.get("iface_eth", "")
    iface_tag = params.get("iface_tag", "0")
    if iface_type == "vlan":
        iface_name = iface_eth + "." + iface_tag
    iface_eth_using = "yes" == params.get("iface_eth_using", "no")
    ping_ip = params.get("ping_ip", "localhost")
    use_exist_iface = "yes" == params.get("use_exist_iface", "no")
    status_error = "yes" == params.get("status_error", "no")
    net_restart = "yes" == params.get("iface_net_restart", "no")
    if ping_ip.count("ENTER"):
        raise error.TestNAError("Please input a valid ip address")
    if iface_name.count("ENTER"):
        raise error.TestNAError("Please input a existing bridge/ethernet name")
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    if vm:
        xml_bak = vm_xml.VMXML.new_from_inactive_dumpxml(vm_name)
    iface_script = NETWORK_SCRIPT + iface_name
    iface_script_bk = os.path.join(test.tmpdir, "iface-%s.bk" % iface_name)
    net_bridge = utils_net.Bridge()
    if use_exist_iface:
        if iface_type == "bridge":
            if iface_name not in net_bridge.list_br():
                raise error.TestError("Bridge '%s' not exists" % iface_name)
            ifaces = net_bridge.get_structure()[iface_name]
            if len(ifaces) < 1:
                # In this situation, dhcp maybe cannot get ip address
                # Unless you use static, we'd better skip such case
                raise error.TestNAError("Bridge '%s' has no interface"
                                        " bridged, perhaps cannot get"
                                        " ipaddress" % iface_name)
    net_iface = utils_net.Interface(name=iface_name)
    iface_is_up = True
    list_option = "--all"
    if use_exist_iface:
        if not libvirt.check_iface(iface_name, "exists", "--all"):
            raise error.TestError("Interface '%s' not exists" % iface_name)
        iface_xml = os.path.join(test.tmpdir, "iface.xml.tmp")
        iface_is_up = net_iface.is_up()
    else:
        # Note, if not use the interface which already exists, iface_name must
        # be equal to the value specified in XML file
        if libvirt.check_iface(iface_name, "exists", "--all"):
            raise error.TestError("Interface '%s' already exists" % iface_name)
        if not iface_xml:
            raise error.TestError("XML file is needed.")
        iface_xml = os.path.join(test.tmpdir, iface_xml)
        create_xml_file(iface_xml, params)

    # Stop NetworkManager as which may conflict with virsh iface commands
    try:
        NM = utils_misc.find_command("NetworkManager")
    except ValueError:
        logging.debug("No NetworkManager service.")
        NM = None
    NM_is_running = False
    if NM is not None:
        NM_service = service.Factory.create_service("NetworkManager")
        NM_is_running = NM_service.status()
        if NM_is_running:
            NM_service.stop()

    # run test cases
    try:
        if use_exist_iface:
            # back up the interface script
            utils.run("cp %s %s" % (iface_script, iface_script_bk))
            # step 1.1
            # dumpxml for interface
            xml = virsh.iface_dumpxml(iface_name, "--inactive",
                                      to_file=iface_xml, debug=True)
            # Step 1.2
            # Destroy interface
            if iface_is_up:
                result = virsh.iface_destroy(iface_name, debug=True)
                libvirt.check_exit_status(result, status_error)

            # Step 1.3
            # Undefine interface
            result = virsh.iface_undefine(iface_name, debug=True)
            libvirt.check_exit_status(result, status_error)
            if not status_error:
                if libvirt.check_iface(iface_name, "exists", list_option):
                    raise error.TestFail("%s is still present." % iface_name)

        # Step 2
        # Define interface
        result = virsh.iface_define(iface_xml, debug=True)
        if iface_type == "bond" and not ping_ip:
            libvirt.check_exit_status(result, True)
            return
        else:
            libvirt.check_exit_status(result, status_error)

        if net_restart:
            network = service.Factory.create_service("network")
            network.restart()

        # After network restart, (ethernet)interface will be started
        if (not net_restart and iface_type in ("bridge", "ethernet")) or\
           (not use_exist_iface and iface_type in ("vlan", "bond")):
            # Step 3
            # List inactive interfaces
            list_option = "--inactive"
            if not status_error:
                if not libvirt.check_iface(iface_name, "exists", list_option):
                    raise error.TestFail("Fail to find %s." % iface_name)

            # Step 4
            # Start interface
            result = virsh.iface_start(iface_name, debug=True)
            if not net_restart and not use_exist_iface and\
               (iface_type == "ethernet" and iface_pro in ["", "dhcp"] or
                    iface_type == "bridge" and iface_pro == "dhcp"):
                libvirt.check_exit_status(result, True)
            else:
                libvirt.check_exit_status(result, status_error)
            if not status_error:
                iface_ip = net_iface.get_ip()
                ping_ip = ping_ip if not iface_ip else iface_ip
                if ping_ip:
                    if not libvirt.check_iface(iface_name, "ping", ping_ip):
                        raise error.TestFail("Ping %s fail." % ping_ip)

        # Step 5
        # List active interfaces
        if use_exist_iface or\
           (iface_pro != "dhcp" and iface_type == "bridge") or\
           (iface_eth_using and iface_type == "vlan"):
            list_option = ""
            if not status_error:
                if not libvirt.check_iface(iface_name, "exists", list_option):
                    raise error.TestFail("Fail to find %s in active "
                                         "interface list" % iface_name)
            if vm:
                iface_mac_list = vm_xml.VMXML.get_iface_dev(vm_name)
                # Before test, detach all interfaces in guest
                for mac in iface_mac_list:
                    iface_info = vm_xml.VMXML.get_iface_by_mac(vm_name, mac)
                    type = iface_info.get('type')
                    virsh.detach_interface(vm_name,
                                           "--type %s --mac %s"
                                           " --config" % (type, mac))
                virsh.attach_interface(vm_name,
                                       "--type %s --source %s"
                                       " --config" % (iface_type, iface_name))
                vm.start()
                try:
                    # Test if guest can be login
                    vm.wait_for_login()
                except remote.LoginError:
                    raise error.TestFail("Cannot login guest with %s" %
                                         iface_name)

        # Step 6
        # Dumpxml for interface
        xml = virsh.iface_dumpxml(iface_name, "", to_file="", debug=True)
        logging.debug("Interface '%s' XML:\n%s", iface_name, xml)

        # Step 7
        # Get interface MAC address by name
        result = virsh.iface_mac(iface_name, debug=True)
        libvirt.check_exit_status(result, status_error)
        if not status_error and result.stdout.strip():
            if not libvirt.check_iface(iface_name, "mac",
                                       result.stdout.strip()):
                raise error.TestFail("Mac address check fail")

        # Step 8
        # Get interface name by MAC address
        # Bridge's Mac equal to bridged interface's mac
        if iface_type not in ("bridge", "vlan") and result.stdout.strip():
            iface_mac = net_iface.get_mac()
            result = virsh.iface_name(iface_mac, debug=True)
            libvirt.check_exit_status(result, status_error)

        # Step 9
        if not use_exist_iface:
            # Step 9.1
            # Destroy interface
            result = virsh.iface_destroy(iface_name, debug=True)
            if not net_restart and\
               iface_type == "ethernet" and iface_pro in ["", "dhcp"] or\
               iface_type == "bridge" and iface_pro == "dhcp":
                libvirt.check_exit_status(result, True)
            else:
                libvirt.check_exit_status(result, status_error)

            # Step 9.2
            # Undefine interface
            result = virsh.iface_undefine(iface_name, debug=True)
            libvirt.check_exit_status(result, status_error)
            list_option = "--all"
            if not status_error:
                if libvirt.check_iface(iface_name, "exists", list_option):
                    raise error.TestFail("%s is still present." % iface_name)
    finally:
        if os.path.exists(iface_xml):
            os.remove(iface_xml)
        if os.path.exists(iface_script):
            os.remove(iface_script)

        if use_exist_iface:
            if not os.path.exists(iface_script):
                utils.run("mv %s %s" % (iface_script_bk, iface_script))
            if iface_is_up and\
               not libvirt.check_iface(iface_name, "exists", ""):
                # Need reload script
                utils.run("ifup %s" % iface_name)
            elif not iface_is_up and libvirt.check_iface(iface_name,
                                                         "exists", ""):
                net_iface.down()
            if vm:
                xml_bak.sync()
        else:
            if libvirt.check_iface(iface_name, "exists", "--all"):
                # Remove the interface
                try:
                    utils_net.bring_down_ifname(iface_name)
                except utils_net.TAPBringDownError:
                    pass
            if iface_type == "bridge":
                if iface_name in net_bridge.list_br():
                    net_bridge.del_bridge(iface_name)
        if NM_is_running:
            NM_service.start()
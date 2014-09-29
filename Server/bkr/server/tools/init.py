
# -*- coding: utf-8 -*-

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# pkg_resources.requires() does not work if multiple versions are installed in 
# parallel. This semi-supported hack using __requires__ is the workaround.
# http://bugs.python.org/setuptools/issue139
# (Fedora/EPEL has python-cherrypy2 = 2.3 and python-cherrypy = 3)
__requires__ = ['CherryPy < 3.0']

import sys
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm.exc import NoResultFound
from bkr.log import log_to_stream
from bkr.server.model import (User, Group, Permission, Hypervisor, KernelType,
        Arch, PowerType, Key, Response, RetentionTag, ConfigItem, UserGroup)
from bkr.server.util import load_config_or_exit
from turbogears.database import session
from os.path import dirname, exists, join
from os import getcwd
import turbogears
from turbogears.database import metadata, get_engine
from optparse import OptionParser
from alembic import config as alembic_config
from alembic import command as alembic_command
from alembic import util as alembic_util

__version__ = '0.1'
__description__ = 'Command line tool for initializing Beaker DB'

def dummy():
    pass

def init_db(user_name=None, password=None, user_display_name=None, user_email_address=None):
    get_engine()
    metadata.create_all()
    session.begin()

    try:
        admin = Group.by_name(u'admin')
    except InvalidRequestError:
        admin     = Group(group_name=u'admin',display_name=u'Admin')
        session.add(admin)

    try:
        lab_controller = Group.by_name(u'lab_controller')
    except InvalidRequestError:
        lab_controller = Group(group_name=u'lab_controller',
                               display_name=u'Lab Controller')
        session.add(lab_controller)

    #Setup User account
    if user_name:
        if password:
            user = User(user_name=user_name.decode('utf8'), password=password.decode('utf8'))
            if user_display_name:
                user.display_name = user_display_name.decode('utf8')
            if user_email_address:
                user.email_address = user_email_address.decode('utf8')
            admin.user_group_assocs.append(UserGroup(user=user, is_owner=True))
        else:
            print "Password must be provided with username"
    elif len(admin.users) == 0:
        print "No admin account exists, please create one with --user"
        sys.exit(1)

    # Create distro_expire perm if not present
    try:
        distro_expire_perm = Permission.by_name(u'distro_expire')
    except NoResultFound:
        distro_expire_perm = Permission(u'distro_expire')
        session.add(distro_expire_perm)

    # Create proxy_auth perm if not present
    try:
        proxy_auth_perm = Permission.by_name(u'proxy_auth')
    except NoResultFound:
        proxy_auth_perm = Permission(u'proxy_auth')
        session.add(proxy_auth_perm)

    # Create tag_distro perm if not present
    try:
        tag_distro_perm = Permission.by_name(u'tag_distro')
    except NoResultFound:
        tag_distro_perm = Permission(u'tag_distro')
        admin.permissions.append(tag_distro_perm)

    # Create stop_task perm if not present
    try:
        stop_task_perm = Permission.by_name(u'stop_task')
    except NoResultFound:
        stop_task_perm = Permission(u'stop_task')
        lab_controller.permissions.append(stop_task_perm)
        admin.permissions.append(stop_task_perm)

    # Create secret_visible perm if not present
    try:
        secret_visible_perm = Permission.by_name(u'secret_visible')
    except NoResultFound:
        secret_visible_perm = Permission(u'secret_visible')
        lab_controller.permissions.append(secret_visible_perm)
        admin.permissions.append(secret_visible_perm)

    #Setup Hypervisors Table
    if Hypervisor.query.count() == 0:
        for h in [u'KVM', u'Xen', u'HyperV', u'VMWare']:
            session.add(Hypervisor(hypervisor=h))

    #Setup kernel_type Table
    if KernelType.query.count() == 0:
        for type in [u'default', u'highbank', u'imx', u'omap', u'tegra']:
            session.add(KernelType(kernel_type=type, uboot=False))
        for type in [u'mvebu']:
            session.add(KernelType(kernel_type=type, uboot=True))

    #Setup base Architectures
    if Arch.query.count() == 0:
        for arch in [u'i386', u'x86_64', u'ia64', u'ppc', u'ppc64', u'ppc64le',
                     u's390', u's390x', u'armhfp', u'aarch64', u'arm']:
            session.add(Arch(arch))

    #Setup base power types
    if PowerType.query.count() == 0:
        for power_type in [u'apc_snmp', u'apc_snmp_then_etherwake',
                u'bladecenter', u'bladepap', u'drac', u'ether_wake', u'hyper-v',
                u'ilo', u'integrity', u'ipmilan', u'ipmitool', u'lpar', u'rsa',
                u'virsh', u'wti']:
            session.add(PowerType(power_type))

    #Setup key types
    if Key.query.count() == 0:
        session.add(Key(u'DISKSPACE',True))
        session.add(Key(u'COMMENT'))
        session.add(Key(u'CPUFAMILY',True))
        session.add(Key(u'CPUFLAGS'))
        session.add(Key(u'CPUMODEL'))
        session.add(Key(u'CPUMODELNUMBER', True))
        session.add(Key(u'CPUSPEED',True))
        session.add(Key(u'CPUVENDOR'))
        session.add(Key(u'DISK',True))
        session.add(Key(u'FORMFACTOR'))
        session.add(Key(u'HVM'))
        session.add(Key(u'MEMORY',True))
        session.add(Key(u'MODEL'))
        session.add(Key(u'MODULE'))
        session.add(Key(u'NETWORK'))
        session.add(Key(u'NR_DISKS',True))
        session.add(Key(u'NR_ETH',True))
        session.add(Key(u'NR_IB',True))
        session.add(Key(u'PCIID'))
        session.add(Key(u'PROCESSORS',True))
        session.add(Key(u'RTCERT'))
        session.add(Key(u'SCRATCH'))
        session.add(Key(u'STORAGE'))
        session.add(Key(u'USBID'))
        session.add(Key(u'VENDOR'))
        session.add(Key(u'XENCERT'))
        session.add(Key(u'NETBOOT_METHOD'))

    #Setup ack/nak reposnses
    if Response.query.count() == 0:
        session.add(Response(response=u'ack'))
        session.add(Response(response=u'nak'))

    if RetentionTag.query.count() == 0:
        session.add(RetentionTag(tag=u'scratch', is_default=1, expire_in_days=30))
        session.add(RetentionTag(tag=u'60days', needs_product=False, expire_in_days=60))
        session.add(RetentionTag(tag=u'120days', needs_product=False, expire_in_days=120))
        session.add(RetentionTag(tag=u'active', needs_product=True))
        session.add(RetentionTag(tag=u'audit', needs_product=True))

    config_items = [
        # name, description, numeric
        (u'root_password', u'Plaintext root password for provisioned systems', False),
        (u'root_password_validity', u"Maximum number of days a user's root password is valid for", True),
        (u'guest_name_prefix', u'Prefix for names of dynamic guests in OpenStack', False),
    ]
    for name, description, numeric in config_items:
        ConfigItem.lazy_create(name=name, description=description, numeric=numeric)
    if ConfigItem.by_name(u'root_password').current_value() is None:
        ConfigItem.by_name(u'root_password').set(u'beaker', user=admin.users[0])

    session.commit()
    session.close()

def get_parser():
    usage = "usage: %prog [options]"
    parser = OptionParser(usage, description=__description__,
                          version=__version__)

    ## Actions
    parser.add_option("-c", "--config", action="store", type="string",
                      dest="configfile", help="location of config file.")
    parser.add_option("-u", "--user", action="store", type="string",
                      dest="user_name", help="username of Admin account")
    parser.add_option("-p", "--password", action="store", type="string",
                      dest="password", help="password of Admin account")
    parser.add_option("-e", "--email", action="store", type="string",
                      dest="email_address", 
                      help="email address of Admin account")
    parser.add_option("-n", "--fullname", action="store", type="string",
                      dest="display_name", help="Full name of Admin account")
    parser.add_option("--downgrade", type="string", metavar='REVISION_IDENTIFIER',
                     help="Downgrade database to a previous version")
    return parser

def do_alembic_command(config, cmd, *args, **kwargs):
    try:
        getattr(alembic_command, cmd)(config, *args, **kwargs)
    except alembic_util.CommandError as e:
        # alembic_util.err() will call sys.exit(-1) to exit
        alembic_util.err(str(e))

def main():
    parser = get_parser()
    opts, args = parser.parse_args()
    load_config_or_exit(opts.configfile)
    log_to_stream(sys.stderr)
    alembic_config_ = alembic_config.Config()
    alembic_config_.set_main_option('script_location', 'bkr.server:alembic')
    alembic_config_.set_main_option('sqlalchemy.url',
                                   turbogears.config.get("sqlalchemy.dburi"))
    if opts.downgrade:
        do_alembic_command(alembic_config_, 'downgrade', opts.downgrade)
    else:
        # if database is empty then initialize it
        if not get_engine().table_names():
            init_db(user_name=opts.user_name, password=opts.password,
                    user_display_name=opts.display_name, user_email_address=opts.email_address)
            do_alembic_command(alembic_config_, 'stamp', 'head')
        else:
            # upgrade to the latest DB version
            do_alembic_command(alembic_config_, 'upgrade', 'head')

if __name__ == "__main__":
    main()

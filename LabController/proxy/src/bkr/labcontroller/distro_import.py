import sys, os
import glob
import xmlrpclib
import string
import ConfigParser
import getopt
from optparse import OptionParser
import urllib2
import calendar
from email.utils import parsedate
import logging
import socket
import copy
from bkr.common.bexceptions import BX
import pprint

def url_exists(url):
    try:
        urllib2.urlopen(url)
    except urllib2.URLError:
        return False
    except urllib2.HTTPError:
        return False
    except IOError, e:
        # errno 21 is you tried to retrieve a directory.  Thats ok. We just
        # want to ensure the path is valid so far.
        if e.errno == 21:
            pass
        else:
            raise
    return True

class SchedulerProxy(object):
    """Scheduler Proxy"""
    def __init__(self, options):
        self.add_distro_cmd = options.add_distro_cmd
        # addDistroCmd = '/var/lib/beaker/addDistro.sh'
        self.proxy = xmlrpclib.ServerProxy('http://localhost:8000',
                                           allow_none=True)

    def add_distro(self, profile):
        return self.proxy.add_distro_tree(profile)

    def run_distro_test_job(self, name=None, tags=[], osversion=None,
                            arches=[], variants=[]):
        if self.is_add_distro_cmd:
            cmd = self._make_add_distro_cmd(name=name,tags=tags,
                                            osversion=osversion,
                                            arches=arches, variants=variants)
            logging.debug(cmd)
            os.system(cmd)
        else:
            raise BX('%s is missing' % self.add_distro_cmd)

    def _make_add_distro_cmd(self, name=None, tags=[],
                             osversion=None, arches=[], variants=[]):
        #addDistro.sh "rel-eng" RHEL6.0-20090626.2 RedHatEnterpriseLinux6.0 x86_64,i386 "Server,Workstation,Client"
        cmd = '%s "%s" "%s" "%s" "%s" "%s"' % (
            self.add_distro_cmd,
            ','.join(tags),
            name,
            osversion,
            ','.join(arches),
            ','.join(variants))
        return cmd

    @property
    def is_add_distro_cmd(self):
        # Kick off jobs automatically
        if os.path.exists(self.add_distro_cmd):
            return True
        return False


class Parser(object):
    """
    base class to use for processing .composeinfo and .treeinfo
    """
    url = None
    parser = None
    last_modified = None

    def parse(self, url):
        self.url = url
        try:
            f = urllib2.urlopen('%s/%s' % (self.url, self.infofile))
            if 'last-modified' in f.headers:
                self.last_modified = calendar.timegm(parsedate(f.headers['last-modified']))
            self.parser = ConfigParser.ConfigParser()
            self.parser.readfp(f)
            f.close()
        except urllib2.URLError:
            return False
        except urllib2.HTTPError:
            return False
        except ConfigParser.MissingSectionHeaderError, e:
            raise BX('%s/%s is not parsable: %s' % (self.url,
                                                      self.infofile,
                                                      e))
        return True

    def get(self, section, key, default=None):
        if self.parser:
            try:
                default = self.parser.get(section, key)
            except (ConfigParser.NoSectionError, ConfigParser.NoOptionError), e:
                if default is None:
                    raise
        return default

    def __repr__(self):
        return '%s/%s' % (self.url, self.infofile)


class Cparser(Parser):
    infofile = '.composeinfo'

class Tparser(Parser):
    infofile = '.treeinfo'

class TparserRhel5(Tparser):
    def get(self, section, key, default=None):
        value = super(TparserRhel5, self).get(section, key, default=default)
        # .treeinfo for RHEL5 incorrectly reports ppc when it should report ppc64
        if section == 'general' and key == 'arch' and value == 'ppc':
            value = 'ppc64'
        return value

class Importer(object):
    def __init__(self, parser):
        self.parser = parser


class ComposeInfoBase(object):
    @classmethod
    def is_importer_for(cls, url):
        parser = Cparser()
        if not parser.parse(url):
            return False
        for r in cls.required:
            if parser.get(r['section'], r['key'], '') == '':
                return False
        for e in cls.excluded:
            if parser.get(e['section'], e['key'], '') != '':
                return False
        return parser

    def run_jobs(self):
        """
        Run a job with the newly imported distro_trees
        """
        arches = []
        variants = []
        for distro_tree in self.distro_trees:
            arches.append(distro_tree['arch'])
            variants.append(distro_tree['variant'])
            name = distro_tree['name']
            tags = distro_tree.get('tags', [])
            osversion = '%s.%s' % (distro_tree['osmajor'],
                                   distro_tree['osminor'])
        self.scheduler.run_distro_test_job(name=name,
                                           tags=tags,
                                           osversion=osversion,
                                           arches=list(set(arches)),
                                           variants=list(set(variants)))


class ComposeInfoLegacy(ComposeInfoBase, Importer):
    """
    [tree]
    arches = i386,x86_64,ia64,ppc64,s390,s390x
    name = RHEL4-U8
    """
    required = [dict(section='tree', key='name'),
               ]
    excluded = [dict(section='product', key='variants'),
               ]
    arches = ['i386', 'x86_64', 'ia64', 'ppc', 'ppc64', 's390', 's390x']
    os_dirs = ['os', 'tree']

    def get_arches(self):
        """ Return a list of arches
        """
        return filter(lambda x: url_exists(os.path.join(self.parser.url,x)) \
                      and x, [arch for arch in self.arches])

    def get_os_dir(self, arch):
        """ Return path to os directory
        """
        base_path = os.path.join(self.parser.url, arch)
        try:
            os_dir = filter(lambda x: url_exists(os.path.join(base_path, x)) \
                            and x, self.os_dirs)[0]
        except IndexError, e:
            raise BX('%s no os_dir found: %s' % (base_path, e))
        return os.path.join(arch, os_dir)

    def process(self, urls, options):
        self.options = options
        self.scheduler = SchedulerProxy(self.options)
        self.distro_trees = []
        for arch in self.get_arches():
            os_dir = self.get_os_dir(arch)
            full_os_dir = os.path.join(self.parser.url, os_dir)
            options = copy.deepcopy(self.options)
            if not options.name:
                options.name = self.parser.get('tree', 'name')
            urls_arch = [os.path.join(url, os_dir) for url in urls]
            # find our repos, but relative from os_dir
            repos = self.find_repos(full_os_dir, arch)
            try:
                build = Build(full_os_dir)
                build.process(urls_arch, options, repos)
            except BX, err:
                logging.warn(err)
            self.distro_trees.append(build.tree)

    def find_repos(self, repo_base, arch):
        """
        RHEL6 repos
        ../../optional/<ARCH>/os/repodata
        ../../optional/<ARCH>/debug/repodata
        ../debug/repodata
        """
        repo_paths = [('debuginfo',
                       'debug',
                       '../debug'),
                      ('optional-debuginfo',
                       'debug',
                       '../optional/%s/debug' % arch),
                      ('optional',
                       'optional',
                       '../../optional/%s/os' % arch),
                     ]
        repos = []
        for repo in repo_paths:
            if url_exists(os.path.join(repo_base,repo[2],'repodata')):
                repos.append(dict(
                                  repoid=repo[0],
                                  type=repo[1],
                                  path=repo[2],
                                 )
                            )
        return repos


class ComposeInfo(ComposeInfoBase, Importer):
    """
[product]
family = RHEL
name = Red Hat Enterprise Linux
variants = Client,ComputeNode,Server,Workstation
version = 7.0

[variant-Client]
arches = x86_64
id = Client
name = Client
type = variant
uid = Client
variants = Client-optional

[variant-Client-optional]
arches = x86_64
id = optional
name = optional
parent = Client
type = optional
uid = Client-optional
variants = 

[variant-Client-optional.x86_64]
arch = x86_64
debuginfo = Client-optional/x86_64/debuginfo
os_dir = Client-optional/x86_64/os
packages = Client-optional/x86_64/os/Packages
parent = Client.x86_64
repository = Client-optional/x86_64/os
sources = Client-optional/source/SRPMS

[variant-Client.x86_64]
arch = x86_64
debuginfo = Client/x86_64/debuginfo
isos = Client/x86_64/iso
os_dir = Client/x86_64/os
packages = Client/x86_64/os/Packages
repository = Client/x86_64/os
source_isos = Client/source/iso
sources = Client/source/SRPMS

[variant-ComputeNode]
arches = x86_64
id = ComputeNode
name = Compute Node
type = variant
uid = ComputeNode
variants = ComputeNode-optional

[variant-ComputeNode-optional]
arches = x86_64
id = optional
name = optional
parent = ComputeNode
type = optional
uid = ComputeNode-optional
variants = 

[variant-ComputeNode-optional.x86_64]
arch = x86_64
debuginfo = ComputeNode-optional/x86_64/debuginfo
os_dir = ComputeNode-optional/x86_64/os
packages = ComputeNode-optional/x86_64/os/Packages
parent = ComputeNode.x86_64
repository = ComputeNode-optional/x86_64/os
sources = ComputeNode-optional/source/SRPMS

[variant-ComputeNode.x86_64]
arch = x86_64
debuginfo = ComputeNode/x86_64/debuginfo
isos = ComputeNode/x86_64/iso
os_dir = ComputeNode/x86_64/os
packages = ComputeNode/x86_64/os/Packages
repository = ComputeNode/x86_64/os
source_isos = ComputeNode/source/iso
sources = ComputeNode/source/SRPMS

[variant-Server]
arches = ppc64,s390x,x86_64
id = Server
name = Server
type = variant
uid = Server
variants = Server-HighAvailability,Server-LoadBalancer,Server-ResilientStorage,Server-ScalableFileSystem,Server-optional

[variant-Server-HighAvailability]
arches = x86_64
id = HighAvailability
name = High Availability
parent = Server
type = addon
uid = Server-HighAvailability
variants = 

[variant-Server-HighAvailability.x86_64]
arch = x86_64
debuginfo = Server/x86_64/debuginfo
os_dir = Server/x86_64/os
packages = Server/x86_64/os/addons/HighAvailability
parent = Server.x86_64
repository = Server/x86_64/os/addons/HighAvailability
sources = Server/source/SRPMS

[variant-Server-LoadBalancer]
arches = x86_64
id = LoadBalancer
name = Load Balancer
parent = Server
type = addon
uid = Server-LoadBalancer
variants = 

[variant-Server-LoadBalancer.x86_64]
arch = x86_64
debuginfo = Server/x86_64/debuginfo
os_dir = Server/x86_64/os
packages = Server/x86_64/os/addons/LoadBalancer
parent = Server.x86_64
repository = Server/x86_64/os/addons/LoadBalancer
sources = Server/source/SRPMS

[variant-Server-ResilientStorage]
arches = x86_64
id = ResilientStorage
name = Resilient Storage
parent = Server
type = addon
uid = Server-ResilientStorage
variants = 

[variant-Server-ResilientStorage.x86_64]
arch = x86_64
debuginfo = Server/x86_64/debuginfo
os_dir = Server/x86_64/os
packages = Server/x86_64/os/addons/ResilientStorage
parent = Server.x86_64
repository = Server/x86_64/os/addons/ResilientStorage
sources = Server/source/SRPMS

[variant-Server-ScalableFileSystem]
arches = x86_64
id = ScalableFileSystem
name = Scalable Filesystem Support
parent = Server
type = addon
uid = Server-ScalableFileSystem
variants = 

[variant-Server-ScalableFileSystem.x86_64]
arch = x86_64
debuginfo = Server/x86_64/debuginfo
os_dir = Server/x86_64/os
packages = Server/x86_64/os/addons/ScalableFileSystem
parent = Server.x86_64
repository = Server/x86_64/os/addons/ScalableFileSystem
sources = Server/source/SRPMS

[variant-Server-optional]
arches = ppc64,s390x,x86_64
id = optional
name = optional
parent = Server
type = optional
uid = Server-optional
variants = 

[variant-Server-optional.ppc64]
arch = ppc64
debuginfo = Server-optional/ppc64/debuginfo
os_dir = Server-optional/ppc64/os
packages = Server-optional/ppc64/os/Packages
parent = Server.ppc64
repository = Server-optional/ppc64/os
sources = Server-optional/source/SRPMS

[variant-Server-optional.s390x]
arch = s390x
debuginfo = Server-optional/s390x/debuginfo
os_dir = Server-optional/s390x/os
packages = Server-optional/s390x/os/Packages
parent = Server.s390x
repository = Server-optional/s390x/os
sources = Server-optional/source/SRPMS

[variant-Server-optional.x86_64]
arch = x86_64
debuginfo = Server-optional/x86_64/debuginfo
os_dir = Server-optional/x86_64/os
packages = Server-optional/x86_64/os/Packages
parent = Server.x86_64
repository = Server-optional/x86_64/os
sources = Server-optional/source/SRPMS

[variant-Server.ppc64]
arch = ppc64
debuginfo = Server/ppc64/debuginfo
isos = Server/ppc64/iso
os_dir = Server/ppc64/os
packages = Server/ppc64/os/Packages
repository = Server/ppc64/os
source_isos = Server/source/iso
sources = Server/source/SRPMS

[variant-Server.s390x]
arch = s390x
debuginfo = Server/s390x/debuginfo
isos = Server/s390x/iso
os_dir = Server/s390x/os
packages = Server/s390x/os/Packages
repository = Server/s390x/os
source_isos = Server/source/iso
sources = Server/source/SRPMS

[variant-Server.x86_64]
arch = x86_64
debuginfo = Server/x86_64/debuginfo
isos = Server/x86_64/iso
os_dir = Server/x86_64/os
packages = Server/x86_64/os/Packages
repository = Server/x86_64/os
source_isos = Server/source/iso
sources = Server/source/SRPMS

[variant-Workstation]
arches = x86_64
id = Workstation
name = Workstation
type = variant
uid = Workstation
variants = Workstation-ScalableFileSystem,Workstation-optional

[variant-Workstation-ScalableFileSystem]
arches = x86_64
id = ScalableFileSystem
name = Scalable Filesystem Support
parent = Workstation
type = addon
uid = Workstation-ScalableFileSystem
variants = 

[variant-Workstation-ScalableFileSystem.x86_64]
arch = x86_64
debuginfo = Workstation/x86_64/debuginfo
os_dir = Workstation/x86_64/os
packages = Workstation/x86_64/os/addons/ScalableFileSystem
parent = Workstation.x86_64
repository = Workstation/x86_64/os/addons/ScalableFileSystem
sources = Workstation/source/SRPMS

[variant-Workstation-optional]
arches = x86_64
id = optional
name = optional
parent = Workstation
type = optional
uid = Workstation-optional
variants = 

[variant-Workstation-optional.x86_64]
arch = x86_64
debuginfo = Workstation-optional/x86_64/debuginfo
os_dir = Workstation-optional/x86_64/os
packages = Workstation-optional/x86_64/os/Packages
parent = Workstation.x86_64
repository = Workstation-optional/x86_64/os
sources = Workstation-optional/source/SRPMS

[variant-Workstation.x86_64]
arch = x86_64
debuginfo = Workstation/x86_64/debuginfo
isos = Workstation/x86_64/iso
os_dir = Workstation/x86_64/os
packages = Workstation/x86_64/os/Packages
repository = Workstation/x86_64/os
source_isos = Workstation/source/iso
sources = Workstation/source/SRPMS

    """
    required = [dict(section='product', key='variants'),
               ]
    excluded = []

    def get_arches(self, variant):
        """ Return a list of arches for variant
        """
        return self.parser.get('variant-%s' %
                                          variant, 'arches').split(',')

    def get_variants(self):
        """ Return a list of variants
        """
        return self.parser.get('product', 'variants').split(',')

    def find_repos(self, repo_base, rpath, variant, arch):
        """ Find all variant repos
        """
        repos = []
        variants = self.parser.get('variant-%s' % variant, 'variants', '')
        if variants:
            for sub_variant in variants.split(','):
                repos.extend(self.find_repos(repo_base, rpath, sub_variant,
                                          arch))

        # Skip addon variants from .composeinfo, we pick these up from 
        # .treeinfo
        repotype = self.parser.get('variant-%s' % variant, 'type', '')
        if repotype == 'addon':
            return repos

        repopath = self.parser.get('variant-%s.%s' % (variant, arch), 
                               'repository', '')
        if repopath:
            repos.append(dict(
                              repoid=variant,
                              type=repotype,
                              path=os.path.join(rpath,repopath),
                             )
                        )

        debugrepopath = self.parser.get('variant-%s.%s' % (variant, arch), 
                               'debuginfo', '')
        if debugrepopath:
            repos.append(dict(
                              repoid='%s-debuginfo' % variant,
                              type='debug',
                              path=os.path.join(rpath,debugrepopath),
                             )
                        )
        return repos

    def process(self, urls, options):
        self.options = options
        self.scheduler = SchedulerProxy(self.options)
        self.distro_trees = []

        for variant in self.get_variants():
            for arch in self.get_arches(variant):
                os_dir = self.parser.get('variant-%s.%s' %
                                              (variant, arch), 'os_dir')
                options = copy.deepcopy(self.options)
                if not options.name:
                    options.name = self.parser.get('product', 'name')

                # our current path relative to the os_dir "../.."
                rpath = os.path.join(*['..' for i in range(0,
                                                len(os_dir.split('/')))])

                # find our repos, but relative from os_dir
                repos = self.find_repos(self.parser.url, rpath, variant, arch)

                urls_variant_arch = [os.path.join(url, os_dir) for url in urls]
                try:
                    build = Build(os.path.join(self.parser.url, os_dir))
                    build.process(urls_variant_arch, options, repos)
                except BX, err:
                    logging.warn(err)
                self.distro_trees.append(build.tree)


class TreeInfoBase(object):
    """
    Base class for TreeInfo methods
    """
    required = [dict(section='general', key='family'),
                dict(section='general', key='version'),
                dict(section='general', key='arch'),
               ]
    excluded = []

    def process(self, urls, options, repos=[]):
        '''
        distro_data = dict(
                name='RHEL-6-U1',
                arches=['i386', 'x86_64'], arch='x86_64',
                osmajor='RedHatEnterpriseLinux6', osminor='1',
                variant='Workstation', tree_build_time=1305067998.6483951,
                urls=['nfs://example.invalid:/RHEL-6-Workstation/U1/x86_64/os/',
                      'file:///net/example.invalid/RHEL-6-Workstation/U1/x86_64/os/',
                      'http://example.invalid/RHEL-6-Workstation/U1/x86_64/os/'],
                repos=[
                    dict(repoid='Workstation', type='os', path=''),
                    dict(repoid='ScalableFileSystem', type='addon', path='ScalableFileSystem/'),
                    dict(repoid='optional', type='addon', path='../../optional/x86_64/os/'),
                    dict(repoid='debuginfo', type='debug', path='../debug/'),
                ],
                images=[
                    dict(type='kernel', path='images/pxeboot/vmlinuz'),
                    dict(type='initrd', path='images/pxeboot/initrd.img'),
                ])

        '''
        self.options = options
        self.scheduler = SchedulerProxy(options)
        self.tree = dict()
        # Make sure all url's end with /
        urls = [os.path.join(url,'') for url in urls]
        self.tree['urls'] = urls
        self.tree['kernel_options'] = ''
        family  = self.parser.get('general', 'family').replace(" ","")
        version = self.parser.get('general', 'version').replace("-",".")
        self.tree['name'] = self.options.name or \
                                   self.parser.get('general', 'name', 
                                   '%s-%s' % (family,version)
                                                    )
        self.tree['variant'] = self.parser.get('general','variant','')
        self.tree['arch'] = self.parser.get('general','arch')
        self.tree['tree_build_time'] = self.parser.get('general','timestamp',
                                                       self.parser.last_modified)
        labels = self.parser.get('general', 'label','')
        self.tree['tags'] = list(set(self.options.tags).union(
                                    set(map(string.strip,
                                    labels and labels.split(',') or []))))
        self.tree['osmajor'] = "%s%s" % (family, version.split('.')[0])
        if version.find('.') != -1:
            self.tree['osminor'] = version.split('.')[1]
        else:
            self.tree['osminor'] = '0'

        arches = self.parser.get('general', 'arches','')
        self.tree['arches'] = map(string.strip,
                                     arches and arches.split(',') or [])
        self.tree['repos'] = repos + self.find_repos()

        # Add install images
        self.tree['images'] = []
        self.tree['images'].append(dict(type='kernel',
                                        path=self.get_kernel_path()))
        self.tree['images'].append(dict(type='initrd',
                                        path=self.get_initrd_path()))

        # if root option is specified then look for stage2
        if self.options.root:
            self.tree['kernel_options'] = 'root=live:%s' % os.path.join(
                                         self.parser.url,
                                         self.parser.get('stage2', 'mainimage')
                                                                       )

        logging.debug('\n%s' % pprint.pformat(self.tree))
        try:
            self.add_to_beaker()
            logging.info('%s added to beaker.' % self.tree['name'])
        except (xmlrpclib.Fault, socket.error), e:
            raise BX('failed to add %s to beaker: %s' % (self.tree['name'],e))

    def add_to_beaker(self):
        self.scheduler.add_distro(self.tree)

    def run_jobs(self):
        arches = [self.tree['arch']]
        variants = [self.tree['variant']]
        name = self.tree['name']
        tags = self.tree.get('tags', [])
        osversion = '%s.%s' % (self.tree['osmajor'],
                               self.tree['osminor'])
        self.scheduler.run_distro_test_job(name=name,
                                           tags=tags,
                                           osversion=osversion,
                                           arches=arches,
                                           variants=variants)


class TreeInfoLegacy(TreeInfoBase, Importer):
    """
    This version of .treeinfo importer has a workaround for missing
    images-$arch sections.
    """
    kernels = ['images/pxeboot/vmlinuz',
               'images/kernel.img',
               'ppc/ppc64/vmlinuz',
               'ppc/iSeries/vmlinux',
              ]
    initrds = ['images/pxeboot/initrd.img',
               'images/initrd.img',
               'ppc/ppc64/ramdisk.image.gz',
               'ppc/iSeries/ramdisk.image.gz',
              ]

    @classmethod
    def is_importer_for(cls, url):
        parser = Tparser()
        if not parser.parse(url):
            return False
        for r in cls.required:
            if parser.get(r['section'], r['key'], '') == '':
                return False
        for e in cls.excluded:
            if parser.get(e['section'], e['key'], '') != '':
                return False
        if not parser.get('general', 'family').startswith("Red Hat Enterprise Linux"):
            return False
        if int(parser.get('general', 'version').split('.')[0]) > 4:
            return False
        return parser

    def get_kernel_path(self):
        try:
            return filter(lambda x: url_exists(os.path.join(self.parser.url,x)) \
                          and x, [kernel for kernel in self.kernels])[0]
        except IndexError, e:
            raise BX('%s no kernel found: %s' % (self.parser.url, e))

    def get_initrd_path(self):
        try:
            return filter(lambda x: url_exists(os.path.join(self.parser.url,x)) \
                          and x, [initrd for initrd in self.initrds])[0]
        except IndexError, e:
            raise BX('%s no kernel found: %s' % (self.parser.url, e))

    def find_repos(self):
        """
        using info from .treeinfo and known locations

        RHEL4 repos
        ../repo-<VARIANT>-<ARCH>/repodata
        ../repo-debug-<VARIANT>-<ARCH>/repodata
        ../repo-srpm-<VARIANT>-<ARCH>/repodata
        arch = ppc64 = ppc

        RHEL3 repos
        ../repo-<VARIANT>-<ARCH>/repodata
        ../repo-debug-<VARIANT>-<ARCH>/repodata
        ../repo-srpm-<VARIANT>-<ARCH>/repodata
        arch = ppc64 = ppc
        """

        # ppc64 arch uses ppc for the repos
        arch = self.tree['arch'].replace('ppc64','ppc')

        repo_paths = [('%s-debuginfo' % self.tree['variant'],
                       'debug',
                       '../debug'),
                      ('%s-debuginfo' % self.tree['variant'],
                       'debug',
                       '../repo-debug-%s-%s' % (self.tree['variant'],
                                                arch)),
                      ('%s-optional-debuginfo' % self.tree['variant'],
                       'debug',
                       '../optional/%s/debug' % arch),
                      ('%s' % self.tree['variant'],
                       'variant',
                       '../repo-%s-%s' % (self.tree['variant'],
                                          arch)),
                      ('%s' % self.tree['variant'],
                       'variant',
                       '.'),
                      ('%s-optional' % self.tree['variant'],
                       'optional',
                       '../../optional/%s/os' % arch),
                      ('VT',
                       'addon',
                       'VT'),
                      ('Server',
                       'addon',
                       'Server'),
                      ('Cluster',
                       'addon',
                       'Cluster'),
                      ('ClusterStorage',
                       'addon',
                       'ClusterStorage'),
                      ('Client',
                       'addon',
                       'Client'),
                      ('Workstation',
                       'addon',
                       'Workstation'),
                     ]
        repos = []
        for repo in repo_paths:
            if url_exists(os.path.join(self.parser.url,repo[2],'repodata')):
                repos.append(dict(
                                  repoid=repo[0],
                                  type=repo[1],
                                  path=repo[2],
                                 )
                            )
        return repos


class TreeInfoRhel5(TreeInfoBase, Importer):
    """
[general]
family = Red Hat Enterprise Linux Server
timestamp = 1209596791.91
totaldiscs = 1
version = 5.2
discnum = 1
label = RELEASED
packagedir = Server
arch = ppc

[images-ppc64]
kernel = ppc/ppc64/vmlinuz
initrd = ppc/ppc64/ramdisk.image.gz
zimage = images/netboot/ppc64.img

[stage2]
instimage = images/minstg2.img
mainimage = images/stage2.img

    """
    @classmethod
    def is_importer_for(cls, url):
        parser = TparserRhel5()
        if not parser.parse(url):
            return False
        for r in cls.required:
            if parser.get(r['section'], r['key'], '') == '':
                return False
        for e in cls.excluded:
            if parser.get(e['section'], e['key'], '') != '':
                return False
        if not parser.get('general', 'family').startswith("Red Hat Enterprise Linux"):
            return False
        if int(parser.get('general', 'version').split('.')[0]) != 5:
            return False
        return parser

    def get_kernel_path(self):
        return self.parser.get('images-%s' % self.tree['arch'],'kernel')

    def get_initrd_path(self):
        return self.parser.get('images-%s' % self.tree['arch'],'initrd')

    def find_repos(self):
        """
        using info from known locations

        RHEL5 repos
        ../debug/repodata
        ./Server
        ./Cluster
        ./ClusterStorage
        ./VT
        ./Client
        ./Workstation
        """

        # ppc64 arch uses ppc for the repos
        arch = self.tree['arch'].replace('ppc64','ppc')

        repo_paths = [('VT',
                       'addon',
                       'VT'),
                      ('Server',
                       'addon',
                       'Server'),
                      ('Cluster',
                       'addon',
                       'Cluster'),
                      ('ClusterStorage',
                       'addon',
                       'ClusterStorage'),
                      ('Client',
                       'addon',
                       'Client'),
                      ('Workstation',
                       'addon',
                       'Workstation'),
                     ]
        repos = []
        for repo in repo_paths:
            if url_exists(os.path.join(self.parser.url,repo[2],'repodata')):
                repos.append(dict(
                                  repoid=repo[0],
                                  type=repo[1],
                                  path=repo[2],
                                 )
                            )
        return repos


class TreeInfoFedora(TreeInfoBase, Importer):
    """

    """
    @classmethod
    def is_importer_for(cls, url):
        parser = Tparser()
        if not parser.parse(url):
            return False
        for r in cls.required:
            if parser.get(r['section'], r['key'], '') == '':
                return False
        for e in cls.excluded:
            if parser.get(e['section'], e['key'], '') != '':
                return False
        if not parser.get('general', 'family').startswith("Fedora"):
            return False
        return parser

    def get_kernel_path(self):
        return self.parser.get('images-%s' % self.tree['arch'],'kernel')

    def get_initrd_path(self):
        return self.parser.get('images-%s' % self.tree['arch'],'initrd')

    def find_repos(self):
        """
        using info from known locations

        """

        repo_paths = [('Fedora',
                       'variant',
                       '.'),
                     ]
        repos = []
        for repo in repo_paths:
            if url_exists(os.path.join(self.parser.url,repo[2],'repodata')):
                repos.append(dict(
                                  repoid=repo[0],
                                  type=repo[1],
                                  path=repo[2],
                                 )
                            )
        return repos


class TreeInfoRhel6(TreeInfoBase, Importer):
    """
[addon-ScalableFileSystem]
identity = ScalableFileSystem/ScalableFileSystem.cert
name = Scalable Filesystem Support
repository = ScalableFileSystem

[addon-ResilientStorage]
identity = ResilientStorage/ResilientStorage.cert
name = Resilient Storage
repository = ResilientStorage

[images-x86_64]
kernel = images/pxeboot/vmlinuz
initrd = images/pxeboot/initrd.img
boot.iso = images/boot.iso

[general]
family = Red Hat Enterprise Linux
timestamp = 1328166952.001091
variant = Server
totaldiscs = 1
version = 6.3
discnum = 1
packagedir = Packages
variants = Server
arch = x86_64

[images-xen]
initrd = images/pxeboot/initrd.img
kernel = images/pxeboot/vmlinuz

[variant-Server]
addons = ResilientStorage,HighAvailability,ScalableFileSystem,LoadBalancer
identity = Server/Server.cert
repository = Server/repodata

[addon-HighAvailability]
identity = HighAvailability/HighAvailability.cert
name = High Availability
repository = HighAvailability

[checksums]
images/pxeboot/initrd.img = sha256:4ffa63cd7780ec0715bd1c50b9eda177ecf28c58094ca519cfb6bb6aca5c225a
images/efiboot.img = sha256:d9ba2cc6fd3286ed7081ce0846e9df7093f5d524461580854b7ac42259c574b1
images/boot.iso = sha256:5e10d6d4e6e22a62cae1475da1599a8dac91ff7c3783fda7684cf780e067604b
images/pxeboot/vmlinuz = sha256:7180f7f46682555cb1e86a9f1fbbfcc193ee0a52501de9a9002c34528c3ef9ab
images/install.img = sha256:85aaf9f90efa4f43475e4828168a3f7755ecc62f6643d92d23361957160dbc69
images/efidisk.img = sha256:e9bf66f54f85527e595c4f3b5afe03cdcd0bf279b861c7a20898ce980e2ce4ff

[stage2]
mainimage = images/install.img

[addon-LoadBalancer]
identity = LoadBalancer/LoadBalancer.cert
name = Load Balancer
repository = LoadBalancer
    """
    @classmethod
    def is_importer_for(cls, url):
        parser = Tparser()
        if not parser.parse(url):
            return False
        for r in cls.required:
            if parser.get(r['section'], r['key'], '') == '':
                return False
        for e in cls.excluded:
            if parser.get(e['section'], e['key'], '') != '':
                return False
        if parser.get('images-%s' % parser.get('general','arch'), 'kernel', '') == '':
            return False
        if parser.get('images-%s' % parser.get('general','arch'), 'initrd', '') == '':
            return False
        if not parser.get('general', 'family').startswith("Red Hat Enterprise Linux"):
            return False
        if int(parser.get('general', 'version').split('.')[0]) != 6:
            return False
        return parser

    def get_kernel_path(self):
        return self.parser.get('images-%s' % self.tree['arch'],'kernel')

    def get_initrd_path(self):
        return self.parser.get('images-%s' % self.tree['arch'],'initrd')

    def find_repos(self):
        """
        using info from .treeinfo
        """

        repos = []
        try:
            repopath = self.parser.get('variant-%s' % self.tree['variant'],
                                       'repository')
            # remove the /repodata from the entry, this should not be there
            repopath = repopath.replace('/repodata','')
            repos.append(dict(
                              repoid=str(self.tree['variant']),
                              type='variant',
                              path=repopath,
                             )
                        )
        except (ConfigParser.NoSectionError, ConfigParser.NoOptionError), e:
            logging.debug('.treeinfo has no repository for variant %s, %s' % (self.parser.url,e))
        try:
            addons = self.parser.get('variant-%s' % self.tree['variant'],
                                     'addons')
            addons = addons and addons.split(',') or []
            for addon in addons:
                repopath = self.parser.get('addon-%s' % addon, 'repository', '')
                if repopath:
                    repos.append(dict(
                                      repoid=addon,
                                      type='addon',
                                      path=repopath,
                                     )
                                )
        except (ConfigParser.NoSectionError, ConfigParser.NoOptionError), e:
            logging.debug('.treeinfo has no addon repos for %s, %s' % (self.parser.url,e))
        return repos


class TreeInfoRHS(TreeInfoBase, Importer):
    """
    Importer for Red Hat Storage

[variant-RHS]
addons = 
identity = RHS/RHS.cert
repository = RHS/repodata

[images-x86_64]
kernel = images/pxeboot/vmlinuz
initrd = images/pxeboot/initrd.img
boot.iso = images/boot.iso

[general]
family = Red Hat Storage
timestamp = 1336067116.493109
variant = RHS
totaldiscs = 1
version = 2.0
discnum = 1
packagedir = Packages
variants = RHS
arch = x86_64

[images-xen]
initrd = images/pxeboot/initrd.img
kernel = images/pxeboot/vmlinuz

[checksums]
images/pxeboot/initrd.img = sha256:30525b91282dff3555b0e7203e10ac46e94dd6e925df95bc0b5442b91f592020
images/efiboot.img = sha256:a89e750492dd419189eb82f513d3c18442d9b159fc237cbe1e9323e511f95186
images/boot.iso = sha256:80a79342c790c58783e41323cfdae6118a1785693773cffe01e2594783da1f61
images/pxeboot/vmlinuz = sha256:0d04f45518d65fd85e2c5884dc9c0254b399ed9623794738986c7dfd1ec27dd2
images/install.img = sha256:d795444e92e27893aec8edf8f45fe39e7306b1ce8379dc9f1c3fb6c126c57e6b
images/efidisk.img = sha256:4d74866a0fb0368cee92e6c0e7a52522eb9cded1d03e1427a4aa2c3a21c4d54f

[stage2]
mainimage = images/install.img

    """
    @classmethod
    def is_importer_for(cls, url):
        parser = Tparser()
        if not parser.parse(url):
            return False
        for r in cls.required:
            if parser.get(r['section'], r['key'], '') == '':
                return False
        for e in cls.excluded:
            if parser.get(e['section'], e['key'], '') != '':
                return False
        if not parser.get('general', 'family').startswith("Red Hat Storage"):
            return False
        return parser

    def get_kernel_path(self):
        return self.parser.get('images-%s' % self.tree['arch'],'kernel')

    def get_initrd_path(self):
        return self.parser.get('images-%s' % self.tree['arch'],'initrd')

    def find_repos(self):
        """
        using info from .treeinfo
        """

        repos = []
        try:
            repopath = self.parser.get('variant-%s' % self.tree['variant'],
                                       'repository')
            # remove the /repodata from the entry, this should not be there
            repopath = repopath.replace('/repodata','')
            repos.append(dict(
                              repoid=str(self.tree['variant']),
                              type='variant',
                              path=repopath,
                             )
                        )
        except (ConfigParser.NoSectionError, ConfigParser.NoOptionError), e:
            logging.debug('.treeinfo has no repository for variant %s, %s' % (self.parser.url,e))
        return repos


class TreeInfoRhel(TreeInfoBase, Importer):
    """
[addon-HighAvailability]
id = HighAvailability
name = High Availability
repository = addons/HighAvailability
uid = Server-HighAvailability

[addon-LoadBalancer]
id = LoadBalancer
name = Load Balancer
repository = addons/LoadBalancer
uid = Server-LoadBalancer

[addon-ResilientStorage]
id = ResilientStorage
name = Resilient Storage
repository = addons/ResilientStorage
uid = Server-ResilientStorage

[addon-ScalableFileSystem]
id = ScalableFileSystem
name = Scalable Filesystem Support
repository = addons/ScalableFileSystem
uid = Server-ScalableFileSystem

[general]
addons = HighAvailability,LoadBalancer,ResilientStorage,ScalableFileSystem
arch = x86_64
family = Red Hat Enterprise Linux
version = 7.0
variant = Server
timestamp = 
name = RHEL-7.0-20120201.0
repository = 

[images-x86_64]
boot.iso = images/boot.iso
initrd = images/pxeboot/initrd.img
kernel = images/pxeboot/vmlinuz

[images-xen]
initrd = images/pxeboot/initrd.img
kernel = images/pxeboot/vmlinuz

    """
    @classmethod
    def is_importer_for(cls, url):
        parser = Tparser()
        if not parser.parse(url):
            return False
        for r in cls.required:
            if parser.get(r['section'], r['key'], '') == '':
                return False
        for e in cls.excluded:
            if parser.get(e['section'], e['key'], '') != '':
                return False
        if parser.get('images-%s' % parser.get('general','arch'), 'kernel', '') == '':
            return False
        if parser.get('images-%s' % parser.get('general','arch'), 'initrd', '') == '':
            return False
        if not parser.get('general', 'family').startswith("Red Hat Enterprise Linux"):
            return False
        return parser

    def find_repos(self):
        """
        using info from .treeinfo find addon repos
        """
        repos = []
        try:
            addons = self.parser.get('general', 'addons')
            addons = addons and addons.split(',') or []
            for addon in addons:
                repopath = self.parser.get('addon-%s' % addon, 'repository', '')
                if repopath:
                    repos.append(dict(
                                      repoid=addon,
                                      type='addon',
                                      path=repopath,
                                     )
                                )
        except (ConfigParser.NoSectionError, ConfigParser.NoOptionError), e:
            logging.debug('no addon repos for %s, %s' % (self.parser.url,e))
        return repos

    def get_kernel_path(self):
        return self.parser.get('images-%s' % self.tree['arch'],'kernel')

    def get_initrd_path(self):
        return self.parser.get('images-%s' % self.tree['arch'],'initrd')


def Build(url):
    logging.info("Importing: %s", url)
    for cls in Importer.__subclasses__():
        parser = cls.is_importer_for(url)
        if parser != False:
            logging.debug("\tImporter %s Matches", cls.__name__)
            return cls(parser)
        else:
            logging.debug("\tImporter %s does not match", cls.__name__)
    raise BX('No valid importer found for %s' % url)

def main():
    parser = OptionParser()
    parser.add_option("-c", "--add-distro-cmd",
                      default="/var/lib/beaker/addDistro.sh",
                      help="Command to run to add a new distro")
    parser.add_option("-n", "--name",
                      default=None,
                      help="Alternate name to use, otherwise we read it from .treeinfo")
    parser.add_option("-t", "--tag",
                      default=[],
                      action="append",
                      dest="tags",
                      help="Additional tags to add")
    parser.add_option("--root",
                      action='store_true',
                      default=False,
                      help="Add root=live: to kernel_options")
    parser.add_option("-r", "--run-jobs",
                      action='store_true',
                      default=False,
                      help="Run automated Jobs")
    parser.add_option("-v", "--debug",
                      action='store_true',
                      default=False,
                      help="show debug messages")
    parser.add_option("-q", "--quiet",
                      action='store_true',
                      default=False,
                      help="less messages")
                      
    (opts, urls) = parser.parse_args()

    LOG_FORMAT = '%(asctime)s - %(levelname)s - %(filename)s - ' \
        '%(funcName)s:%(lineno)s - %(message)s'
    if opts.debug:
        LOG_LEVEL = logging.DEBUG
    elif opts.quiet:
        LOG_LEVEL = logging.CRITICAL
    else:
        LOG_LEVEL = logging.INFO
        LOG_FORMAT = '%(message)s'

    formatter = logging.Formatter(LOG_FORMAT)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    logger = logging.getLogger('')
    logger.addHandler(stdout_handler)
    logger.setLevel(LOG_LEVEL)

    if not urls:
        logging.critical('No location(s) specified!')
        sys.exit(10)
    # primary method is what we use to import the distro, we look for 
    #         .composeinfo or .treeinfo at that location.  Because of this
    #         nfs can't be the primary install method.
    primary_methods = ['http',
                       'ftp',
                      ]
    primary = None
    for url in urls:
        method = url.split(':',1)[0]
        if method in primary_methods:
            primary = url
            break
    if primary == None:
        logging.critical('missing a valid primary installer! %s, are valid install methods' % ' and '.join(primary_methods))
        sys.exit(20)

    try:
        build = Build(primary)
        build.process(urls, opts)
    except BX, err:
        logging.critical(err)
        sys.exit(30)
    if opts.run_jobs:
        logging.info('running jobs.')
        build.run_jobs()

if __name__ == '__main__':
    main()

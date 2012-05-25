
import os, os.path
import errno
import socket
import logging
import tempfile
import shutil
import shlex
import pipes
from contextlib import contextmanager
import urllib
import urllib2
from bkr.labcontroller.config import get_conf

logger = logging.getLogger(__name__)

def get_tftp_root():
    return get_conf().get('TFTP_ROOT', '/var/lib/tftpboot')

# Would be nice if Python did this for us: http://bugs.python.org/issue8604
@contextmanager
def atomically_replaced_file(dest_path, mode=0644):
    (fd, temp_path) = tempfile.mkstemp(prefix=os.path.basename(dest_path),
            dir=os.path.dirname(dest_path))
    try:
        f = os.fdopen(fd, 'w')
        yield f
        f.flush()
        os.fchmod(fd, mode)
        os.rename(temp_path, dest_path)
    except:
        # Clean up the temp file, but suppress any exception if the cleaning fails
        try:
            os.unlink(temp_path)
        finally:
            pass
        # Now re-raise the original exception
        raise

def siphon(src, dest):
    while True:
        chunk = src.read(4096)
        if not chunk:
            break
        dest.write(chunk)

def unlink_ignore(path):
    """
    Unlinks the given path, but succeeds if it doesn't exist.
    """
    try:
        os.unlink(path)
    except OSError, e:
        if e.errno != errno.ENOENT:
            raise

def makedirs_ignore(path, mode):
    """
    Creates the given directory (and any parents), but succeeds if it already
    exists.
    """
    try:
        os.makedirs(path, mode)
    except OSError, e:
        if e.errno != errno.EEXIST:
            raise

def write_ignore(path, content):
    """
    Creates and populates the given file, but leaves it untouched (and
    succeeds) if the file already exists.
    """
    try:
        f = open(path, 'wx') # not sure this is portable to Python 3!
    except IOError, e:
        if e.errno != errno.EEXIST:
            raise
    else:
        logger.debug("%s didn't exist, writing it", path)
        f.write(content)

def cached_filename(url):
    return urllib.quote(url, '') # ugly, but safe

def clean_image_cache():
    cached_images_dir = os.path.join(get_tftp_root(), 'cached-images')
    try:
        entries = os.listdir(cached_images_dir)
    except OSError, e:
        if e.errno == errno.ENOENT:
            return
        else:
            raise
    max_entries = get_conf().get('IMAGE_CACHE_MAX_ENTRIES', 20)
    if len(entries) <= max_entries:
        return
    ctimes = {}
    for entry in entries:
        try:
            stat = os.stat(os.path.join(cached_images_dir, entry))
        except OSError, e:
            if e.errno == errno.ENOENT:
                continue
            else:
                raise
        ctimes[entry] = stat.st_ctime
    old_entries = sorted(entries,
            key=lambda entry: ctimes[entry],
            reverse=True)[max_entries:]
    for entry in old_entries:
        logger.debug('Cleaning %s from image cache', entry)
        unlink_ignore(os.path.join(cached_images_dir, entry))

def fetch_images(kernel_url, initrd_url, fqdn):
    images_dir = os.path.join(get_tftp_root(), 'images', fqdn)
    makedirs_ignore(images_dir, 0755)
    cached_images_dir = os.path.join(get_tftp_root(), 'cached-images')

    if get_conf().get('IMAGE_CACHE', False):
        # Try the cache first.
        try:
            os.link(os.path.join(cached_images_dir, cached_filename(kernel_url)),
                    os.path.join(images_dir, 'kernel'))
            os.link(os.path.join(cached_images_dir, cached_filename(initrd_url)),
                    os.path.join(images_dir, 'initrd'))
            logger.debug('Using cached images for %s', fqdn)
            return
        except OSError, e:
            if e.errno != errno.ENOENT:
                raise
        # Okay, fall back to fetching...

    logger.debug('Fetching kernel %s for %s', kernel_url, fqdn)
    with atomically_replaced_file(os.path.join(images_dir, 'kernel')) as dest:
        siphon(urllib2.urlopen(kernel_url), dest)
    logger.debug('Fetching initrd %s for %s', initrd_url, fqdn)
    with atomically_replaced_file(os.path.join(images_dir, 'initrd')) as dest:
        siphon(urllib2.urlopen(initrd_url), dest)

    if get_conf().get('IMAGE_CACHE', False):
        logger.debug('Linking fetched images for %s to cache', fqdn)
        makedirs_ignore(cached_images_dir, 0755)
        try:
            # Do them in the opposite order to above
            os.link(os.path.join(images_dir, 'initrd'),
                    os.path.join(cached_images_dir, cached_filename(initrd_url)))
            os.link(os.path.join(images_dir, 'kernel'),
                    os.path.join(cached_images_dir, cached_filename(kernel_url)))
        except OSError, e:
            if e.errno != errno.EEXIST:
                raise
        clean_image_cache()

def clear_images(fqdn):
    images_dir = os.path.join(get_tftp_root(), 'images', fqdn)
    logger.debug('Removing images for %s', fqdn)
    shutil.rmtree(images_dir, ignore_errors=True)

def pxe_basename(fqdn):
    # pxelinux uses upper-case hex IP address for config filename
    ipaddr = socket.gethostbyname(fqdn)
    return '%02X%02X%02X%02X' % tuple(int(octet) for octet in ipaddr.split('.'))

# Unfortunately the initrd kernel arg needs some special handling. It can be
# supplied from the Beaker side (e.g. a system-specific driver disk) but we
# also supply the main initrd here which we have fetched from the distro.
def extract_initrd_arg(kernel_options):
    """
    Returns a tuple of (initrd arg value, rest of kernel options). If there was
    no initrd= arg, the result will be (None, untouched kernel options).
    """
    initrd = None
    tokens = []
    for token in shlex.split(kernel_options):
        if token.startswith('initrd='):
            initrd = token[len('initrd='):]
        else:
            tokens.append(pipes.quote(token))
    if initrd:
        return (initrd, ' '.join(tokens))
    else:
        return (None, kernel_options)

def configure_pxelinux(fqdn, kernel_options):
    pxe_dir = os.path.join(get_tftp_root(), 'pxelinux.cfg')
    if not os.path.exists(pxe_dir):
        os.makedirs(pxe_dir, mode=0755)

    basename = pxe_basename(fqdn)
    initrd, kernel_options = extract_initrd_arg(kernel_options)
    if initrd:
        initrd = '/images/%s/initrd,%s' % (fqdn, initrd)
    else:
        initrd = '/images/%s/initrd' % fqdn
    config = '''default linux
prompt 0
timeout 100
label linux
    kernel /images/%s/kernel
    ipappend 2
    append initrd=%s %s netboot_method=pxe
''' % (fqdn, initrd, kernel_options)
    logger.debug('Writing pxelinux config for %s as %s', fqdn, basename)
    with atomically_replaced_file(os.path.join(pxe_dir, basename)) as f:
        f.write(config)

def clear_pxelinux(fqdn):
    pxe_dir = os.path.join(get_tftp_root(), 'pxelinux.cfg')
    basename = pxe_basename(fqdn)
    logger.debug('Removing pxelinux config for %s as %s', fqdn, basename)
    unlink_ignore(os.path.join(pxe_dir, basename))
    write_ignore(os.path.join(pxe_dir, 'default'), '''default local
prompt 0
timeout 0
label local
    localboot 0
''')

def configure_efigrub(fqdn, kernel_options):
    grub_dir = os.path.join(get_tftp_root(), 'grub')
    if not os.path.exists(grub_dir):
        os.makedirs(grub_dir, mode=0755)
        os.symlink('../images', os.path.join(grub_dir, 'images'))

    basename = pxe_basename(fqdn)
    initrd, kernel_options = extract_initrd_arg(kernel_options)
    if initrd:
        initrd = ' '.join(['/images/%s/initrd' % fqdn] + initrd.split(','))
    else:
        initrd = '/images/%s/initrd' % fqdn
    config = '''default 0
timeout 10
title Beaker scheduled job for %s
    root (nd)
    kernel /images/%s/kernel %s netboot_method=efigrub
    initrd %s
''' % (fqdn, fqdn, kernel_options, initrd)
    logger.debug('Writing grub config for %s as %s', fqdn, basename)
    with atomically_replaced_file(os.path.join(grub_dir, basename)) as f:
        f.write(config)

def clear_efigrub(fqdn):
    grub_dir = os.path.join(get_tftp_root(), 'grub')
    basename = pxe_basename(fqdn)
    logger.debug('Removing grub config for %s as %s', fqdn, basename)
    unlink_ignore(os.path.join(grub_dir, basename))

def configure_zpxe(fqdn, kernel_options):
    zpxe_dir = os.path.join(get_tftp_root(), 's390x')
    if not os.path.exists(zpxe_dir):
        os.makedirs(zpxe_dir, mode=0755)

    kernel_options = "%s netboot_method=zpxe" % kernel_options
    # The structure of these files is dictated by zpxe.rexx,
    # Cobbler's "pseudo-PXE" for zVM on s390(x).
    # XXX I don't think multiple initrds are supported?
    logger.debug('Writing zpxe index file for %s', fqdn)
    with atomically_replaced_file(os.path.join(zpxe_dir, 's_%s' % fqdn)) as f:
        f.write('/images/%s/kernel\n/images/%s/initrd\n\n' % (fqdn, fqdn))
    logger.debug('Writing zpxe parm file for %s', fqdn)
    with atomically_replaced_file(os.path.join(zpxe_dir, 's_%s_parm' % fqdn)) as f:
        # must be wrapped at 80 columns
        rest = kernel_options
        while rest:
            f.write(rest[:80] + '\n')
            rest = rest[80:]
    logger.debug('Writing zpxe conf file for %s', fqdn)
    with atomically_replaced_file(os.path.join(zpxe_dir, 's_%s_conf' % fqdn)) as f:
        pass # unused, but zpxe.rexx fetches it anyway

def clear_zpxe(fqdn):
    zpxe_dir = os.path.join(get_tftp_root(), 's390x')
    logger.debug('Writing "local" zpxe index file for %s', fqdn)
    with atomically_replaced_file(os.path.join(zpxe_dir, 's_%s' % fqdn)) as f:
        f.write('local\n') # XXX or should we just delete it??
    logger.debug('Removing zpxe parm file for %s', fqdn)
    unlink_ignore(os.path.join(zpxe_dir, 's_%s_parm' % fqdn))
    logger.debug('Removing zpxe conf file for %s', fqdn)
    unlink_ignore(os.path.join(zpxe_dir, 's_%s_conf' % fqdn))

def configure_elilo(fqdn, kernel_options):
    basename = '%s.conf' % pxe_basename(fqdn)
    # XXX I don't think multiple initrds are supported?
    config = '''relocatable

image=/images/%s/kernel
    label=netinstall
    append="%s netboot_method=elilo"
    initrd=/images/%s/initrd
    read-only
    root=/dev/ram
''' % (fqdn, kernel_options, fqdn)
    logger.debug('Writing elilo config for %s as %s', fqdn, basename)
    with atomically_replaced_file(os.path.join(get_tftp_root(), basename)) as f:
        f.write(config)

def clear_elilo(fqdn):
    basename = '%s.conf' % pxe_basename(fqdn)
    unlink_ignore(os.path.join(get_tftp_root(), basename))

def configure_yaboot(fqdn, kernel_options):
    yaboot_conf_dir = os.path.join(get_tftp_root(), 'etc')
    if not os.path.exists(yaboot_conf_dir):
        os.makedirs(yaboot_conf_dir, mode=0755)
    ppc_dir = os.path.join(get_tftp_root(), 'ppc')
    if not os.path.exists(ppc_dir):
        os.makedirs(ppc_dir, mode=0755)

    basename = pxe_basename(fqdn).lower()
    # XXX I don't think multiple initrds are supported?
    config = '''init-message="Beaker scheduled job for %s"
timeout=80
delay=10
default=linux

image=/images/%s/kernel
    label=linux
    initrd=/images/%s/initrd
    append="%s netboot_method=yaboot"
''' % (fqdn, fqdn, fqdn, kernel_options)
    logger.debug('Writing yaboot config for %s as %s', fqdn, basename)
    with atomically_replaced_file(os.path.join(yaboot_conf_dir, basename)) as f:
        f.write(config)
    logger.debug('Creating yaboot symlink for %s as %s', fqdn, basename)
    os.symlink('../yaboot', os.path.join(ppc_dir, basename))

def clear_yaboot(fqdn):
    basename = pxe_basename(fqdn).lower()
    logger.debug('Removing yaboot config for %s as %s', fqdn, basename)
    unlink_ignore(os.path.join(get_tftp_root(), 'etc', basename))
    logger.debug('Removing yaboot symlink for %s as %s', fqdn, basename)
    unlink_ignore(os.path.join(get_tftp_root(), 'ppc', basename))

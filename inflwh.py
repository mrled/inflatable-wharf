#!/usr/bin/env python3

"""
Perforated cardboard is the. uhh. the entry point. For a box of Lego.
Sorry
"""

import argparse
import datetime
import enum
import json
import logging
import os
import pwd
import re
import subprocess
import textwrap
import time
import sys

from cryptography import x509
from cryptography.hazmat.backends import default_backend

## Generic helper classes/functions


SCRIPTDIR = os.path.dirname(os.path.realpath(__file__))
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s')
LOGGER = logging.getLogger(__name__)


class RunningOnWindowsError(BaseException):
    pass


class HomeDirectoryStickyBitSet(BaseException):
    pass


class ResolvedPath(str):
    """Resolve a path

    Intended to be passed as a type= option to add_argument()
    (which is why it is a class and not a function)
    """
    def __new__(cls, path):
        return str.__new__(cls, os.path.realpath(os.path.normpath(os.path.expanduser(path))))


def idb_excepthook(type, value, tb):
    """Call an interactive debugger in post-mortem mode

    If you do "sys.excepthook = idb_excepthook", then an interactive debugger
    will be spawned at an unhandled exception
    """
    if hasattr(sys, 'ps1') or not sys.stderr.isatty():
        sys.__excepthook__(type, value, tb)
    else:
        import pdb, traceback
        traceback.print_exception(type, value, tb)
        pdb.pm()


def sticky_bit_set(path):
    return os.stat(path).st_mode & 0o1000 == 0o1000


def abswalk(path):
    """Return a list of absolute paths to files and directories
    """
    result = []
    for root, dirs, files in os.walk(path):
        for dirname in dirs:
            result.append(f"{os.path.join(root, dirname)}{os.path.sep}")
        for filename in files:
            result.append(f"{os.path.join(root, filename)}")
    result.sort()
    return result


def useradd(username, uid, gid, home, groupname=None, shell='/bin/sh'):
    """Create a user

    Use the Busybox adduser and addgroup commands
    """
    if sticky_bit_set(home):
        raise HomeDirectoryStickyBitSet()
    if not groupname:
        groupname = username
    try:
        subprocess.run(['addgroup', '-g', gid, '-S', groupname])
        LOGGER.debug(f"Successfull created group {groupname}")
    except subprocess.CalledProcessError:
        LOGGER.debug(f"Group {groupname} already exists")
    try:
        subprocess.run(
            ['adduser', '-S', '-u', uid, '-G', groupname, '-s', shell, '-h', home, username])
        LOGGER.debug(f"Successfull created user {username}")
    except subprocess.CalledProcessError:
        LOGGER.debug(f"User {username} already exists")


def dropprivs(uid, gid, umask=0o077):
    """Drop privileges from root
    """

    try:
        if os.getuid() != 0:
            return
        os.setgroups([])   # Do not inherit root groups
        os.setgid(gid)
        os.setuid(uid)
        os.umask(umask)
        user_pwd = pwd.getpwuid(1001)
        os.environ['HOME'] = user_pwd.pw_dir
        os.environ['SHELL'] = user_pwd.pw_shell
        os.chdir(user_pwd.pw_dir)

    except AttributeError:
        LOGGER.error("We are probably on Windows, cannot drop privileges")
        raise RunningOnWindowsError()


## Implementation classes/functions


class LegoAction(enum.Enum):
    Renew = "renew"
    Run = "run"
    NoAction = None


class LegoBox():
    """A LEGO box, you see, is a wrapper for lego

    (Sorry)

    Initializer arguments:
    lego_dir            The location to save the certificates
    letsencrypt_email   An email address to send to Let's Encrypt
    domain              The domain to try to register for
    dns_authenticator   The DNS hosting provider
    letsencrypt_server  Either "staging" or "production"
    min_cert_validity   If a cert exists but is valid for less than this number of days, renew it
    """

    def __init__(
            self, lego_dir, letsencrypt_email, domain, dns_authenticator, letsencrypt_server,
            min_cert_validity=25):
        self.lego_dir = lego_dir
        self.letsencrypt_email = letsencrypt_email
        self.domain = domain
        self.dns_authenticator = dns_authenticator
        self.letsencrypt_server = letsencrypt_server
        self.min_cert_validity = min_cert_validity

        self.certificate_path = os.path.join(self.lego_dir, 'certificates', f'{self.domain}.crt')

    @property
    def command(self):
        command = [
            'lego', '--accept-tos',
            '--path', self.lego_dir,
            '--email', self.letsencrypt_email,
            '--domains', self.domain,
            '--dns', self.dns_authenticator,
        ]

        if self.letsencrypt_server == "staging":
            command += ['--server', 'https://acme-staging.api.letsencrypt.org/directory']
        elif self.letsencrypt_server == "production":
            pass
        else:
            raise Exception(f"Unknown Let's Encrypt server '{self.letsencrypt_server}'")

        command += [self.action]

        return command

    @property
    def action(self):
        if os.path.exists(self.certificate_path):
            return "renew"
        else:
            return "run"

    def run(self, whatif=False, env=os.environ.copy()):
        LOGGER.info("Running lego as [{cmd}] with environment\n{env}".format(
            cmd=' '.join(self.command),
            env='\n  '.join([f"{k} = {v}" for k, v in env.items()])))

        if not whatif:
            proc = subprocess.run(self.command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            LOGGER.info(
                f"lego exited with {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")

        acme_dir_contents = '\n  '.join(abswalk(self.lego_dir))
        LOGGER.info(f"Current contents of {self.lego_dir}:\n{acme_dir_contents}")

    def shouldrun(self, min_cert_validity=25):
        try:
            expires = get_cert_expiration(self.certificate_path)
            expiresdelta = expires - datetime.datetime.now()
            if expiresdelta.days <= min_cert_validity:
                LOGGER.info(
                    "Determined lego should be run because the cert expires in "
                    f"{expiresdelta.days} days")
                return True
            else:
                LOGGER.info(
                    "Determined lego should NOT be run because the cert expires in "
                    f"{expiresdelta.days} days")
                return False
        except FileNotFoundError:
            LOGGER.info("Determined lego should be run because the cert does not exist locally")
            return True


# def getlegovars(variables=os.environ):
#     """Get a dict of name=value environment variable pairs relating to lego

#     Variables are assumed to be used by the lego command if the name starts with ACME_,
#     or if it is found in the output of 'lego dnshelp'
#     """

#     def islegovar(varname, dnshelp):
#         return (
#             varname.startswith('ACME_') or
#             (re.match('^([0-9A-Z]*_*)*$', varname) and varname in dnshelp))

#     dnshelp = subprocess.run(['lego', 'dnshelp'], stdout=subprocess.PIPE).stdout.decode()
#     legovars = {}
#     for varname, value in variables.items():
#         if islegovar(varname, dnshelp):
#             legovars[varname] = value
#     return legovars


def get_cert_expiration(certificate):
    with open(certificate, 'rb') as certfile:
        cert_contents = certfile.read()
    cert = x509.load_pem_x509_certificate(cert_contents, default_backend())
    return cert.not_valid_after


# def maybe_run_lego(
#         lego_dir, letsencrypt_email, domain, dns_authenticator, letsencrypt_server,
#         whatif=False):
#     """legobox() is, you see, a wrapper for lego

#     (Sorry)

#     Arguments:
#     lego_dir            The location to save the certificates
#     letsencrypt_email   An email address to send to Let's Encrypt
#     domain              The domain to try to register for
#     dns_authenticator   The DNS hosting provider
#     letsencrypt_server  Either "staging" or "production"
#     whatif              Do not actually run, but show what would have been run
#     """

#     action = calculate_lego_action(lego_dir, domain)
#     if action is LegoAction.NoAction:
#         return

#     command = [
#         'lego', '--accept-tos',
#         '--path', lego_dir,
#         '--email', letsencrypt_email,
#         '--domains', domain,
#         '--dns', dns_authenticator,
#     ]

#     if letsencrypt_server == "staging":
#         command += ['--server', 'https://acme-staging.api.letsencrypt.org/directory']
#     elif letsencrypt_server == "production":
#         pass
#     else:
#         raise Exception(f"Unknown Let's Encrypt server '{letsencrypt_server}'")

#     command += [action.value]


def eventloop(legobox, min_cert_validity=25, whatif=False, sleepsecs=300):
    while True:
        if legobox.shouldrun():
            legobox.run(whatif=whatif)

        time.sleep(sleepsecs)


def parseargs(*args, **kwargs):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--debug", "-d", action='store_true',
        help="Include debugging output and start the debugger on unhandled exceptions")
    parser.add_argument(
        '--acme-dir', default=os.environ.get("ACME_DIR"),
        help='The script directory. This must match the value set during container build time')
    parser.add_argument(
        '--acme-username', default=os.environ.get("ACME_USER"),
        help='The name of the user to run lego')
    parser.add_argument(
        '--acme-uid', default=int(os.environ.get("ACME_USER_ID")), type=int,
        help='The UID for the user to run lego')
    parser.add_argument(
        '--acme-gid', default=int(os.environ.get("ACME_GROUP_ID")), type=int,
        help='The primary GID for the user to run lego')
    parser.add_argument(
        '--letsencrypt-email', default=os.environ.get("ACME_LETSENCRYPT_EMAIL"),
        help="Email address to register with Let's Encrypt")
    parser.add_argument(
        '--letsencrypt-server', default=os.environ.get("ACME_LETSENCRYPT_SERVER"),
        choices=['staging', 'production'],
        help="The Let's Encrypt API endpoint to use - staging or production")
    parser.add_argument(
        '--dns-authenticator', default=os.environ.get("ACME_DNS_AUTHENTICATOR"),
        help="The DNS hosting service used to complete the ACME challenges")
    parser.add_argument(
        '--domain', default=os.environ.get("ACME_DOMAIN"),
        help="The domain to request certificates for")
    # TODO: Do I need this?
    # parser.add_argument(
    #     '--lego-box-envfile-path', type=ResolvedPath,
    #     default=ResolvedPath('/etc/lego-box-environment'),
    #     help=(
    #         'The path to the lego-box environment path. '
    #         'Hard-coded to the default value in other files - do not change'))
    parser.add_argument(
        '--only-once', action='store_true',
        help="Run lego once and then exit")
    parser.add_argument(
        '--min-cert-validity', type=int, default=25,
        help="If the certificate exists but expires in less than this number of days, renew")
    parser.add_argument(
        '--whatif', action='store_true',
        help="Do not actually request certificates, but print what would be done")

    return parser.parse_args()


def main(*args, **kwargs):
    parsed = parseargs(args, kwargs)

    if parsed.debug:
        sys.excepthook = idb_excepthook
        LOGGER.setLevel(logging.DEBUG)

    try:
        useradd(parsed.acme_username, parsed.acme_uid, parsed.acme_gid, parsed.acme_home)
    except HomeDirectoryStickyBitSet:
        LOGGER.error(textwrap.dedent(f"""
            The ACME_DIR was set to '{parsed.acme_dir}'

            However, that directory has the sticky bit set. This is not supported,
            because we use ACME_DIR as the home directory for the user inside the container.

            The most likely reason this is happening is that you have probably used /tmp as
            the source for the ACME_DIR volume, by e.g. passing
                --volume=/tmp:/srv/inflatable-wharf
            Use a different directory, without the sticky bit set, as the source for ACME_DIR.
            """))
        raise

    dropprivs(parsed.acme_uid, parsed.acme_gid, umask=0o007)

    box = LegoBox(
        parsed.acme_dir, parsed.letsencrypt_email, parsed.domain, parsed.dns_authenticator,
        parsed.letsencrypt_server)

    if parsed.only_once:
        if box.shouldrun():
            box.run(whatif=parsed.whatif)
    else:
        eventloop(box, whatif=parsed.whatif)

    # if parsed.frequency == "once":
    #     legobox(
    #         parsed.acme_dir, parsed.letsencrypt_email, parsed.domain, parsed.dns_authenticator,
    #         parsed.letsencrypt_server)
    #     raise Exception("Write the rest of the program, idiot")

    # if parsed.frequency in ('monthly', 'devel'):
        # context = daemon.DaemonContext()
        # context.uid = parsed.acme_uid
        # context.gid = parsed.acme_gid
        # with context:
        #     raise Exception("Write the rest of the program, idiot")

    # legovarsj = json.dumps(getlegovars(), sort_keys=True, indent=4)
    # with open(parsed.lego_box_envfile_path, 'w') as efp:
    #     efp.write(legovarsj)
    # print(f"Saved environment variables to {parsed.lego_box_envfile_path}:")
    # print(legovarsj)


if __name__ == '__main__':
    sys.exit(main(*sys.argv))

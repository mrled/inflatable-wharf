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
import re
import subprocess
import textwrap
import time
import sys

from cryptography import x509
from cryptography.hazmat.backends import default_backend

## Generic helper classes/functions


SCRIPTDIR = os.path.dirname(os.path.realpath(__file__))
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s]\t%(levelname)s:\t%(message)s',
    datefmt='%Y-%m-%d %H:%M:%S')
LOGGER = logging.getLogger(__name__)


class RunningOnWindowsError(BaseException):
    """Indicate that we are running on Windows and cannot proceed
    """
    pass


class HomeDirectoryStickyBitSet(BaseException):
    """Indicate that the sticky bit was set on the home directory
    """
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
    """Test whether the sticky bit is set for a given path
    """
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


def indent(instr, spaces=2):
    """Indent each line of some text

    instr:      The input text
    spaces:     The number of spaces to indent each line
    """
    string = instr.decode() if hasattr(instr, 'decode') else instr
    return '\n'.join([f"{' '*spaces}{line}" for line in string.split('\n')])


def subprocess_run_log(command, env=os.environ.copy()):
    """Run and log a command

    command     A list making up a command and its arguments
    env         An optional dictionary of environment variables; defaults to this process's env

    Returns the CompletedProcess object if the process exits with a zer return code
    Throws subprocess.CalledProcessError if the process exites with a nonzero return code
    """
    proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    LOGGER.debug("{cmdname} exited with code {rc}\n{out}\n{err}".format(
        cmdname=command[0],
        rc=proc.returncode,
        out=f"STDOUT:\n{indent(proc.stdout)}" if proc.stdout else "STDOUT: NONE",
        err=f"STDERR:\n{indent(proc.stderr)}" if proc.stderr else "STDERR: NONE"))
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, command, output=proc.stdout, stderr=proc.stderr)
    return proc


def useradd(username, uid, gid, home, groupname=None, shell='/bin/sh'):
    """Create a user

    Use the Busybox adduser and addgroup commands

    username        Name of the new user
    uid             UID for the new user
    gid             GID for the new user
    groupname       Name of the new user group; defaults to username
    shell           Shell for new user; defaults to /bin/sh
    """
    if sticky_bit_set(home):
        raise HomeDirectoryStickyBitSet()
    if not groupname:
        groupname = username
    subprocess_run_log(['addgroup', '-g', str(gid), '-S', groupname])
    subprocess_run_log(
        ['adduser', '-S', '-u', str(uid), '-G', groupname, '-s', shell, '-h', home, username])


def dropprivs(uid, gid, umask=0o077):
    """Drop privileges from root

    uid     Change to this UID
    gid     Change to this GID
    umask   Set umask to this value
    """

    try:
        import pwd
    except ModuleNotFoundError:
        LOGGER.error("We are probably on Windows, cannot drop privileges")
        raise RunningOnWindowsError()

    try:
        getuid = os.getuid
        setgroups = os.setgroups
        setgid = os.setgid
        setuid = os.setuid
    except AttributeError:
        LOGGER.error("We are probably on Windows, cannot drop privileges")
        raise RunningOnWindowsError()

    if getuid() != 0:
        return
    setgroups([])   # Do not inherit root groups
    setgid(gid)
    setuid(uid)
    os.umask(umask)
    user_pwd = pwd.getpwuid(uid)
    os.environ['HOME'] = user_pwd.pw_dir
    os.environ['SHELL'] = user_pwd.pw_shell
    os.chdir(user_pwd.pw_dir)


## Implementation classes/functions


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
    docker_secrets      Secrets to look up and pass as environment variables to lego
    """

    def __init__(
            self, lego_dir, letsencrypt_email, domain, dns_authenticator, letsencrypt_server,
            min_cert_validity=25, additional_env_file=None):
        self.lego_dir = lego_dir
        self.letsencrypt_email = letsencrypt_email
        self.domain = domain
        self.dns_authenticator = dns_authenticator
        self.letsencrypt_server = letsencrypt_server
        self.min_cert_validity = min_cert_validity
        self.additional_env_file = additional_env_file

        self.certificate_path = os.path.join(self.lego_dir, 'certificates', f'{self.domain}.crt')

    @property
    def command(self):
        """The command to pass to subprocess.run().
        """
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
        """The action to pass to the lego command.
        """
        if os.path.exists(self.certificate_path):
            return "renew"
        else:
            return "run"

    @property
    def env(self):
        """The environment to pass to the lego command.

        Include secrets.
        """
        env = os.environ.copy()
        if self.additional_env_file:
            env.update(parse_env_file(self.additional_env_file))
        return env

    def run(self, whatif=False):
        """Run the lego command.

        whatif      Do not actually run lego, but show what would have run
        """
        LOGGER.info("Running lego in {mode} mode as [{cmd}] with environment\n{env}".format(
            mode="WHATIF" if whatif else "OPERATIONAL",
            cmd=' '.join(self.command),
            env='\n'.join([f"  {k} = {v}" for k, v in self.env.items()])))

        if not whatif:
            subprocess_run_log(self.command, env=self.env)

        acme_dir_contents = '\n'.join(abswalk(self.lego_dir))
        LOGGER.info(f"Current contents of {self.lego_dir}:\n{indent(acme_dir_contents)}")

    def shouldrun(self, min_cert_validity=25):
        """Test whether certificates should be requested/renewed

        min_cert_validity   If cert exists but is invalid this many days into the future, renew it
        """
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


def parse_env_file(path):
    """Parse a shell environment file

    A shell environment file is a file containing NAME=VALUE environment variables
    from e.g. the shell's env command.

    Note that this is *extremely* basic and does not support comments anywhere or 
    """
    retdict = {}
    with open(path) as ef:
        for line in ef.readlines():
            if len(line) > 0:
                key, value = line.split('=', 1)
                retdict[key.strip()] = value.strip()
    return retdict


def get_cert_expiration(certificate):
    """Get the certificate expiration date as a DateTime object
    """
    with open(certificate, 'rb') as certfile:
        cert_contents = certfile.read()
    cert = x509.load_pem_x509_certificate(cert_contents, default_backend())
    return cert.not_valid_after


def eventloop(legobox, min_cert_validity=25, whatif=False, sleepsecs=10):
    """The inflatable-wharf event loop

    legobox             A LegoBox() instance
    min_cert_validity   If a cert is not valid for this many days into the future, renew
    whatif              If True, do not actually run lego
    sleepsecs           Number of seconds to sleep between iterations of the event loop
    """
    while True:
        if legobox.shouldrun():
            LOGGER.debug("Event loop fired, running lego...")
            legobox.run(whatif=whatif)
        else:
            LOGGER.debug("Event loop fired, but should not run lego")

        time.sleep(sleepsecs)


def parseargs(*args, **kwargs):
    """Parse command-line arguments.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--debug", "-d", action='store_true',
        help=(
            "Include debugging output and start the debugger on unhandled exceptions "
            "(implies --verbose)"))
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Include debugging output")
    parser.add_argument(
        '--logfile', default=None, type=ResolvedPath,
        help="The path to the log file. Defaults to acme.log in the ACME directory")
    parser.add_argument(
        '--acme-dir', default=ResolvedPath("/srv/inflatable-wharf"), type=ResolvedPath,
        help='The script directory. This must match the volume set in Dockerfile.')
    parser.add_argument(
        '--acme-username', default="acme",
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
    parser.add_argument(
        '--only-once', action='store_true',
        help="Run lego once and then exit")
    parser.add_argument(
        '--additional-env-file', help=(
            'The path to an additional file containing environment variables. '
            'The variables should be in KEY=VALUE format.'
            'Intended for use with Docker secrets in a Docker Swarm.'))
    parser.add_argument(
        '--min-cert-validity', type=int, default=25,
        help="If the certificate exists but expires in less than this number of days, renew")
    parser.add_argument(
        '--whatif', action='store_true',
        help="Do not actually request certificates, but print what would be done")

    parsed = parser.parse_args()

    if not parsed.logfile:
        parsed.logfile = os.path.join(parsed.acme_dir, 'acme.log')

    return parsed


def main(*args, **kwargs):
    """Entrypoint for this script.
    """
    parsed = parseargs(args, kwargs)

    filehandler = logging.FileHandler(parsed.logfile)
    filehandler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '[%(asctime)s]\t%(levelname)s:\t%(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    filehandler.setFormatter(formatter)
    LOGGER.addHandler(filehandler)

    if parsed.verbose or parsed.debug:
        LOGGER.setLevel(logging.DEBUG)
    if parsed.debug:
        sys.excepthook = idb_excepthook

    try:
        useradd(parsed.acme_username, parsed.acme_uid, parsed.acme_gid, parsed.acme_dir)
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
        parsed.letsencrypt_server, parsed.additional_env_file)

    if parsed.only_once:
        if box.shouldrun():
            LOGGER.info("Arguments indicated a single run, running...")
            box.run(whatif=parsed.whatif)
        else:
            LOGGER.info(
                "Arguments indicated a single run, "
                "but certs already exist and do not yet need to be renewed.")
    else:
        eventloop(box, whatif=parsed.whatif)


if __name__ == '__main__':
    sys.exit(main(*sys.argv))

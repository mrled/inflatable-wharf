#!/usr/bin/env python3

"""
Perforated cardboard is the. uhh. the entry point. For a box of Lego.
Sorry
"""

import argparse
import datetime
import json
import logging
import os
import re
import subprocess
import textwrap
import sys

import daemon


## Generic helper classes/functions


SCRIPTDIR = os.path.dirname(os.path.realpath(__file__))
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s')
LOGGER = logging.getLogger(__name__)


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


def envlines(environment):
    """Return a list of key=value lines for an ItemsView
    """
    lines = []
    for varname, value in environment.items():
        lines += [f"{varname} = {value}"]
    return lines


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


def useradd(username, uid, gid, home, shell='/bin/sh'):
    """Create an Alpine Linux user and primary group
    """
    try:
        subprocess.run(['addgroup', '-g', gid, '-S', username])
        LOGGER.debug(f"Successfull created group {username}")
    except subprocess.CalledProcessError:
        LOGGER.debug(f"Group {username} already exists")
    try:
        subprocess.run(
            ['adduser', '-S', '-u', uid, '-G', username, '-s', shell, '-h', home, username])
        LOGGER.debug(f"Successfull created user {username}")
    except subprocess.CalledProcessError:
        LOGGER.debug(f"User {username} already exists")


## Implementation classes/functions


def getlegovars(variables=os.environ):
    """Get a dict of name=value environment variable pairs relating to lego

    Variables are assumed to be used by the lego command if the name starts with ACME_,
    or if it is found in the output of 'lego dnshelp'
    """

    def islegovar(varname, dnshelp):
        return (
            varname.startswith('ACME_') or
            (re.match('^([0-9A-Z]*_*)*$', varname) and varname in dnshelp))

    dnshelp = subprocess.run(['lego', 'dnshelp'], stdout=subprocess.PIPE).stdout.decode()
    legovars = {}
    for varname, value in variables.items():
        if islegovar(varname, dnshelp):
            legovars[varname] = value
    return legovars


def legobox(
        lego_dir, letsencrypt_email, domain, dnshost, letsencrypt_server, action,
        whatif=False):
    """legobox() is, you see, a wrapper for lego

    (Sorry)

    Arguments:
    lego_dir            The location to save the certificates
    letsencrypt_email   An email address to send to Let's Encrypt
    domain              The domain to try to register for
    dnshost             The DNS hosting provider
    letsencrypt_server  Either "staging" or "production"
    whatif              Do not actually run, but show what would have been run
    """

    command = [
        'lego', '--accept-tos',
        '--path', lego_dir,
        '--email', letsencrypt_email,
        '--domains', domain,
        '--dns', dnshost,
    ]
    if letsencrypt_server == "staging":
        command += ['--server', 'https://acme-staging.api.letsencrypt.org/directory']
    elif letsencrypt_server == "production":
        pass
    else:
        raise Exception(f"Unknown Let's Encrypt server '{letsencrypt_server}'")
    if os.path.exists(os.path.join(lego_dir, 'certificates', f'{domain}.key')):
        command += 'renew'
    else:
        command += 'run'

    LOGGER.info("Running lego as [{cmd}] with environment\n{env}".format(
        cmd=' '.join(command),
        env='\n  '.join(envlines)))

    if whatif:
        LOGGER.info("Running in whatif mode, nothing to do")
    else:
        proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        LOGGER.info(
            f"lego exited with {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")

    acme_dir_contents = '\n  '.join(abswalk(lego_dir))
    LOGGER.info(f"Current contents of {lego_dir}:\n{acme_dir_contents}")


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
    # TODO: Do I need this?
    parser.add_argument(
        '--lego-box-envfile-path', type=ResolvedPath,
        default=ResolvedPath('/etc/lego-box-environment'),
        help=(
            'The path to the lego-box environment path. '
            'Hard-coded to the default value in other files - do not change'))
    parser.add_argument(
        '--frequency', required=True, choices=['monthly', 'devel', 'once'],
        help=(
            'How often to run lego. '
            '"monthly" means to run lego once per month. '
            '"devel" means to show how lego would be run without running it, once per minute. '
            '"once" means to run lego one time only.'))

    return parser.parse_args()


def main(*args, **kwargs):
    parsed = parseargs(args, kwargs)

    if parsed.debug:
        sys.excepthook = idb_excepthook
        LOGGER.setLevel(logging.DEBUG)

    if sticky_bit_set(parsed.acme_dir):
        msg = textwrap.dedent(f"""
            The ACME_DIR was set to '{parsed.acme_dir}'

            However, that directory has the sticky bit set. This is not supported,
            because we use ACME_DIR as the home directory for the user inside the container.

            The most likely reason this is happening is that you have probably used /tmp as
            the source for the ACME_DIR volume, by e.g. passing
                --volume=/tmp:/srv/inflatable-wharf
            Use a different directory, without the sticky bit set, as the source for ACME_DIR.
            """)
        print(msg)
        raise Exception("Sticky bit set on ACME_DIR")

    useradd(parsed.acme_username, parsed.acme_uid, parsed.acme_gid, parsed.acme_home)

    if parsed.frequency in ('monthly', 'devel'):
        context = daemon.DaemonContext()
        context.uid = parsed.acme_uid
        context.gid = parsed.acme_gid
        with context:
            raise Exception("Write the rest of the program, idiot")

    # legovarsj = json.dumps(getlegovars(), sort_keys=True, indent=4)
    # with open(parsed.lego_box_envfile_path, 'w') as efp:
    #     efp.write(legovarsj)
    # print(f"Saved environment variables to {parsed.lego_box_envfile_path}:")
    # print(legovarsj)


if __name__ == '__main__':
    sys.exit(main(*sys.argv))

    # with daemon.DaemonContext():
    #     do_main_program()


#!/usr/bin/env python3

"""
Perforated cardboard is the. uhh. the entry point. For a box of Lego.
Sorry
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import textwrap
import sys

import daemon


## Generic helper classes/functions


class ResolvedPath(str):
    """Resolve a path

    Intended to be passed as a type= option to add_argument()
    (which is why it is a class and not a function)
    """
    def __new__(cls, path):
        return str.__new__(cls, os.path.realpath(os.path.normpath(os.path.expanduser(path))))


def sticky_bit_set(path):
    return os.stat(path).st_mode & 0o1000 == 0o1000


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


def newcrontab(frequency, legoboxpath):
    """Generate a new lego-box crontab

    frequency       The frequency to run the cronjob
                    'monthly'       Run once per month, starting today
                    'devel'         Show how to run lego once per minute,
                                    but do not actually run it
                    'once'          Run only once
    """

    day_of_month = datetime.datetime.now().day
    # Make sure we don't skip February lol
    if day_of_month > 28:
        day_of_month = 28

    # Cron format:
    #
    # * * * * *     command to execute
    # | | | | ^---- day of week 0-6 (sun-sat) (7 is also Sunday on some systems)
    # | | | ^------ month 1-12
    # | | ^-------- day of month 1-31
    # | ^---------- hour 0-23
    # ^------------ minute 0-59

    if frequency == "monthly":
        return f"* * {day_of_month} * * {legoboxpath}"
    elif frequency == "devel":
        return f"* * * * * {legoboxpath} --whatif"
    elif frequency == "once":
        return ""
    else:
        raise Exception(f"Unknown value for frequency '{frequency}'")


def parseargs(*args, **kwargs):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--acme-dir', default=os.environ.get("ACME_DIR"),
        help='The script directory. This must match the value set during container build time')
    parser.add_argument(
        '--acme-username', default=os.environ.get("ACME_USER"),
        help='The name of the user to run lego')
    parser.add_argument(
        '--acme-uid', default=os.environ.get("ACME_USER_ID"),
        help='The UID for the user to run lego')
    parser.add_argument(
        '--acme-gid', default=os.environ.get("ACME_GROUP_ID"),
        help='The primary GID for the user to run lego')
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
        raise Exception("Stick bit set on ACME_DIR")

    subprocess.run(['addgroup', '-g', parsed.acme_gid, '-S', parsed.acme_username])
    subprocess.run([
        'adduser', '-S', '-u', parsed.acme_uid, '-G', parsed.acme_username,
        '-s', '/bin/sh', '-h', parsed.acme_dir, parsed.acme_username])
    idp = subprocess.run(['id', parsed.acme_username], stdout=subprocess.PIPE)
    grepp = subprocess.run(['grep', parsed.acme_username, '/etc/passwd'], stdout=subprocess.PIPE)

    print("")
    print(f"> id {parsed.acme_username}")
    print(idp.stdout.decode())
    print(f"> grep {parsed.acme_username} /etc/passwd")
    print(grepp.stdout.decode())

    legovarsj = json.dumps(getlegovars(), sort_keys=True, indent=4)
    with open(parsed.lego_box_envfile_path, 'w') as efp:
        efp.write(legovarsj)
    print(f"Saved environment variables to {parsed.lego_box_envfile_path}:")
    print(legovarsj)

    legoboxpath = "/usr/local/bin/lego-box.sh"
    crontab = newcrontab(parsed.frequency, legoboxpath)

    # # Make sure logfile permissions are ok
    # touch "$ACME_LOGFILE"
    # chown "$ACME_USER:$ACME_USER" "$ACME_LOGFILE"

    subprocess.run([legoboxpath, '--whatif'])
    subprocess.run([legoboxpath])

    if crontab != "":
        subprocess.run(['crontab', '-'], input=crontab.encode())
        # Run crond in the background
        subprocess.run(['crond', '-b'])
        # Tail the ACME logfile forever
        subprocess.run(['tail', '-f', parsed.acme_logfile])
    else:
        print("No crontab set, nothing to do...")


if __name__ == '__main__':
    sys.exit(main(*sys.argv))

    # with daemon.DaemonContext():
    #     do_main_program()


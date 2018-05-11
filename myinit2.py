#!/sbin/my_init_python -u

import argparse
import errno
import logging
import os
import signal
import sys


KILL_PROCESS_TIMEOUT = 5
KILL_ALL_PROCESSES_TIMEOUT = 5


logging.basicConfig(level=logging.WARNING, format='[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s')
LOGGER = logging.getLogger(__name__)


terminated_child_processes = {}

## Stupid Windows syntax shim
# Does NOT currently allow for running this script on Windows!
# But it does let me write the goddamn thing in VS Code on Windows without errors
# (Python exposes different module members for platform stuff on Unix vs Windows)
try:
    alarm = signal.alarm
except AttributeError:
    def alarm(time):
        pass
try:
    SIGKILL = signal.SIGKILL
except AttributeError:
    SIGKILL = 0
try:
    SIGALRM = signal.SIGALRM
except AttributeError:
    SIGALRM = 0
try:
    WEXITSTATUS = os.WEXITSTATUS
except AttributeError:
    def WEXITSTATUS(status):
        pass


class SignalHandlers(object):

    @staticmethod
    def sigterm(signum, frame):
        """Ignore SIGTERM and SIGINT, and raise a KeyboardInterrupt
        """
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        raise KeyboardInterrupt('SIGTERM')

    @staticmethod
    def sigint(signum, frame):
        """Ignore SIGTERM and SIGINT, and raise a KeyboardInterrupt
        """
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        raise KeyboardInterrupt('SIGINT')

    @staticmethod
    def sigalrm(signum, frame):
        raise AlarmException('Alarm')


class AlarmException(Exception):
    pass


# Waits for the child process with the given PID, while at the same time
# reaping any other child processes that have exited (e.g. adopted child
# processes that have terminated).
def waitpid_reap_other_children(pid):
    global terminated_child_processes

    status = terminated_child_processes.get(pid)
    if status:
        # A previous call to waitpid_reap_other_children(),
        # with an argument not equal to the current argument,
        # already waited for this process. Return the status
        # that was obtained back then.
        del terminated_child_processes[pid]
        return status

    done = False
    status = None
    while not done:
        try:
            this_pid, status = os.waitpid(-1, 0)
            if this_pid == pid:
                done = True
            else:
                # Save status for later.
                terminated_child_processes[this_pid] = status
        except OSError as e:
            if e.errno == gitECHILD or e.errno == errno.ESRCH:
                return None
            else:
                raise
    return status


def stop_child_process(name, pid, signo=signal.SIGTERM, time_limit=KILL_PROCESS_TIMEOUT):
    LOGGER.info("Shutting down %s (PID %d)..." % (name, pid))
    try:
        os.kill(pid, signo)
    except OSError:
        pass
    alarm(time_limit)
    try:
        try:
            waitpid_reap_other_children(pid)
        except OSError:
            pass
    except AlarmException:
        LOGGER.warn("%s (PID %d) did not shut down in time. Forcing it to exit." % (name, pid))
        try:
            os.kill(pid, SIGKILL)
        except OSError:
            pass
        try:
            waitpid_reap_other_children(pid)
        except OSError:
            pass
    finally:
        alarm(0)


def run_command_killable(*argv):
    filename = argv[0]
    status = None
    pid = os.spawnvp(os.P_NOWAIT, filename, argv)
    try:
        status = waitpid_reap_other_children(pid)
    except BaseException:
        LOGGER.warn("An error occurred. Aborting.")
        stop_child_process(filename, pid)
        raise
    if status != 0:
        if status is None:
            LOGGER.error("%s exited with unknown status\n" % filename)
        else:
            LOGGER.error("%s failed with status %d\n" % (filename, WEXITSTATUS(status)))
        sys.exit(1)


def kill_all_processes(time_limit):
    LOGGER.info("Killing all processes...")
    try:
        os.kill(-1, signal.SIGTERM)
    except OSError:
        pass
    alarm(time_limit)
    try:
        # Wait until no more child processes exist.
        done = False
        while not done:
            try:
                os.waitpid(-1, 0)
            except OSError as e:
                if e.errno == errno.ECHILD:
                    done = True
                else:
                    raise
    except AlarmException:
        LOGGER.warn("Not all processes have exited in time. Forcing them to exit.")
        try:
            os.kill(-1, SIGKILL)
        except OSError:
            pass
    finally:
        alarm(0)


def parseargs(*args, **kwargs):
    parser = argparse.ArgumentParser(description='Initialize the system')

    parser.add_argument(
        'main_command', metavar='MAIN_COMMAND', type=str, nargs='*',
        help='The main command to run. (default: runit)')
    parser.add_argument(
        '--no-kill-all-on-exit', action='store_true',
        help = "Don't kill all processes on the system upon exiting")
    parser.add_argument(
        '--quiet', action='store_true',
        help='Only print warnings and errors')

    return parser.parse_args(*args, **kwargs)


def old_my_init_main(args):
    exit_code = None
    exit_status = None

    LOGGER.info("Running %s..." % " ".join(args.main_command))
    pid = os.spawnvp(os.P_NOWAIT, args.main_command[0], args.main_command)
    try:
        exit_code = waitpid_reap_other_children(pid)
        if exit_code is None:
            LOGGER.info("%s exited with unknown status." % args.main_command[0])
            exit_status = 1
        else:
            exit_status = WEXITSTATUS(exit_code)
            LOGGER.info("%s exited with status %d." % (args.main_command[0], exit_status))
    except KeyboardInterrupt:
        stop_child_process(args.main_command[0], pid)
        raise
    except BaseException:
        LOGGER.warn("An error occurred. Aborting.")
        stop_child_process(args.main_command[0], pid)
        raise
    sys.exit(exit_status)


def main(*args, **kwargs):
    parsed = parseargs(*args, **kwargs)

    if parsed.quiet:
        LOGGER.setLevel(logging.DEBUG)

    if parsed.skip_runit and len(parsed.main_command) == 0:
        LOGGER.error("When --skip-runit is given, you must also pass a main command.")
        sys.exit(1)

    # Run main function.
    signal.signal(signal.SIGTERM, SignalHandlers.sigterm)
    signal.signal(signal.SIGINT, SignalHandlers.sigint)
    signal.signal(SIGALRM, SignalHandlers.sigalrm)

    try:
        old_my_init_main(parsed)
    except KeyboardInterrupt:
        LOGGER.warn("Init system aborted.")
        exit(2)
    finally:
        if not parsed.no_kill_all_on_exit:
            kill_all_processes(KILL_ALL_PROCESSES_TIMEOUT)


if __name__ == '__main__':
    sys.exit(main(*sys.argv))

#!/usr/bin/python2
# encoding=utf-8
from __future__ import print_function
import dbus
import argparse
import operator
import logging
import sys

def get_base_iface(obj):
    return dbus.Interface(obj, dbus_interface="org.mpris.MediaPlayer2")

def get_player_iface(obj):
    return dbus.Interface(obj, dbus_interface="org.mpris.MediaPlayer2.Player")

def get_player(bus, player=None, allow_activate=False):
    if player is None and allow_activate:
        raise ValueError("Misconfiguration: won't activate random player")

    if player is None:
        logging.info("No player passed to get_player, searching for mpris implementation")
        names = bus.list_names()
        for name in names:
            if name.startswith("org.mpris.MediaPlayer2."):
                logging.debug("picked player {0}".format(name))
                return bus.get_object(name, "/org/mpris/MediaPlayer2")
    else:
        logging.info("specific player passed, looking for matching name")
        names = bus.list_names() if not allow_activate else bus.list_activatable_names()
        bus_name = "org.mpris.MediaPlayer2."+player
        if bus_name not in names:
            raise KeyError(bus_name)
        return bus.get_object(bus_name, "/org/mpris/MediaPlayer2")

def play(obj):
    """Resume or start playback"""
    get_player_iface(obj).Play()

def toggle(obj):
    """Toggle between play and pause mode"""
    get_player_iface(obj).PlayPause()

def pause(obj):
    """Pause playback if it isn't already paused"""
    get_player_iface(obj).Pause()

def next_track(obj):
    """Skip the current track and continue with the next one"""
    get_player_iface(obj).Next()

def prev_track(obj):
    """Return to the previous track"""
    get_player_iface(obj).Previous()

def stop(obj):
    """Stop playback"""
    get_player_iface(obj).Stop()

def raise_window(obj):
    """Raise the window of the media player"""
    get_base_iface(obj).Raise()

commands = {
    "play": play,
    "toggle": toggle,
    "pause": pause,
    "next": next_track,
    "prev": prev_track,
    "stop": stop,
    "raise": raise_window
}

class ListCommands(argparse.Action):
    def __init__(self,
                 option_strings=None,
                 dest=None,
                 const=None,
                 default=None,
                 required=False,
                 help=None,
                 metavar=None):
        super(ListCommands, self).__init__(
            option_strings=option_strings,
            dest=dest,
            nargs=0,
            const=const,
            default=default,
            required=required,
            help=help)

    def __call__(self, parser, namespace, values, option_string):
        if values:
            raise argparse.ArgumentError("fnord")

        parser.print_help()
        print("available commands:")
        print("\n".join(
            "{kw} -- {doc}".format(kw=kw, doc=func.__doc__)
            for kw, func in commands.items()
        ))
        parser.exit(0)

class Command(object):
    def __init__(self, cmdmap):
        self.cmdmap = cmdmap

    def __repr__(self):
        return "control command"

    def __call__(self, arg):
        try:
            return self.cmdmap[arg]
        except KeyError as err:
            raise ValueError("no such command: {0!s}".format(err))

if __name__ == "__main__":
    parser = argparse.ArgumentParser("""\
Control a media player implementing the mpris spec using the command
line.""")

    parser.add_argument(
        "-p", "--player",
        metavar="NAME",
        help="Name of the player. This actually has to be the dbus names' suffix, which usually is the same as the media players executable name.",
        dest="player",
        default=None
    )
    parser.add_argument(
        "-a", "--activate",
        action="store_true",
        default=False,
        help="If the player is not running, activate it. This requires a valid --player argument."
    )
    parser.add_argument(
        "-l", "--list-commands",
        help="Print a list of available commands with brief meaning and exit",
        action=ListCommands
    )
    parser.add_argument(
        "-d", "--debug",
        help="Enable debug output",
        action="store_true",
        default=False,
        dest="debug"
    )
    parser.add_argument(
        "command",
        metavar="COMMAND",
        type=Command(commands),
        help="Command to execute, for a list of valid commands, refer to -l"
    )

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARN)

    bus = dbus.SessionBus()
    try:
        obj = get_player(bus, args.player, args.activate)
    except KeyError as err:
        if args.activate:
            print("Player {} isn't available on this system (or not available for activation (hi banshee!))".format(err), file=sys.stderr)
        else:
            print("Player {} isn't running (you might want to try -a)".format(err), file=sys.stderr)
        sys.exit(1)
    except ValueError as err:
        print(str(err), file=sys.stderr)
        sys.exit(1)
    args.command(obj)

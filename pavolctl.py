#!/usr/bin/python3
"""
Use this script to control the volume of the current active (or any
other sink).
"""
import os
import sys
import subprocess
import argparse

class PAConfig(object):
    def __init__(self):
        dump = subprocess.check_output(["pacmd", "dump"]).decode("ascii")
        self.config = [line.split() for line in dump.split("\n")[2:-2] if len(line.strip())]
        del dump

    def findDefaultSink(self):
        for line in reversed(self.config):
            if line[0] == "set-default-sink":
                return line[1]
        return None

    def findVolume(self, sink):
        for line in reversed(self.config):
            if line[0] == "set-sink-volume" and line[1] == sink:
                return int(line[2], 16) / 65536
        return None

    def findMute(self, sink):
        for line in reversed(self.config):
            if line[0] == "set-sink-mute" and line[1] == sink:
                return line[2] == "yes"
        return None

    def _issueSetting(self, cmd):
        subprocess.check_call(["pactl"] + cmd)

    def setSinkVolume(self, sink, vol):
        cmd = ["set-sink-volume", sink, "0x{0:x}".format(int(vol*65536))]
        self._issueSetting(cmd)

    def setSinkMute(self, sink, muted):
        cmd = ["set-sink-mute", sink, "yes" if muted else "no"]
        self._issueSetting(cmd)

def boolword(s):
    s = s.strip().lower()
    if s == "true" or s == "yes" or s == "y" or s == "1":
        return True
    elif s == "false" or s == "no" or s == "n" or s == "0":
        return False
    else:
        raise ValueError('"{0}" is not a valid boolean value.'.format(s))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-s", "--sink",
        metavar="SINK",
        default=None,
        help="Sink on which the actions should take effect (default sink is default)"
    )

    subparsers = parser.add_subparsers()
    parse_setVolume = subparsers.add_parser("set-volume")
    parse_setVolume.add_argument(
        "-r", "--relative",
        dest="relative",
        action="store_true",
        help="If set, the volume is treated as relative to the current one."
    )
    parse_setVolume.add_argument(
        "volume",
        metavar="VOLUME",
        type=float,
        help="Volume to set. Volumes are in the range from 0 (muted) to 1 (blasting your ears off)."
    )

    parse_setMute = subparsers.add_parser("set-mute")
    group_muteArg = parse_setMute.add_mutually_exclusive_group(required=True)
    group_muteArg.add_argument(
        "-t", "--toggle",
        action="store_true",
        help="Toggle muted status."
    )
    group_muteArg.add_argument(
        "mute",
        metavar="BOOL",
        nargs="?",
        default=None,
        type=boolword,
        help="If BOOL is 'true', 'yes' or '1', the sink will be muted, otherwise it will be unmuted."
    )

    args = parser.parse_args(sys.argv[1:])
    config = PAConfig()

    sink = args.sink or config.findDefaultSink()
    if "volume" in args:
        if args.relative:
            volume = config.findVolume(sink)
            volume += args.volume
        else:
            volume = args.volume
            if not 0 <= volume <= 1:
                raise ValueError("Volume must be in the range of 0 and 1 for absolute mode.")
        config.setSinkVolume(sink, volume)
    elif "mute" in args:
        if args.toggle:
            config.setSinkMute(sink, not config.findMute(sink))
        else:
            config.setSinkMute(sink, args.mute)

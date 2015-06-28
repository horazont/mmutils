#!/usr/bin/python3
# File name: transcoder.py
# This file is part of: mmutils
#
# LICENSE
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at
# your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# FEEDBACK & QUESTIONS
#
# For feedback and questions about mmutils please e-mail one of the
# authors named in the AUTHORS file.
########################################################################

import abc
import subprocess
import re
import logging
import os
import sys
import time
import math

devnull = open("/dev/null", "wb")
devzero = open("/dev/zero", "rb")

logger = logging.getLogger()

class DummySubprocess:
    def poll(self):
        return 0

    def wait(self):
        return 0

    def kill(self):
        pass

    def term(self):
        pass

    stdout = devzero

class TaskHandle:
    @abc.abstractmethod
    def poll(self):
        """
        Return the tasks status.

        Check if the task has finished. If so, return the returncode, which must
        be 0 for success and any other integer value for failure. If the task
        has not returned yet, return :data:`None`.
        """
        return super().poll()

    @abc.abstractmethod
    def wait(self):
        """
        Wait for the task to finish.

        Return value is the same as for :meth:`poll`.
        """
        return super().wait()

    @abc.abstractmethod
    def term(self):
        """
        Gracefully terminate the current process.
        """
        return super().term()

class SubprocessHandle(TaskHandle, subprocess.Popen):
    def skip_init(self):
        self.poll = lambda: DummySubprocess.poll(self)
        self.wait = lambda: DummySubprocess.wait(self)
        self.kill = lambda: DummySubprocess.kill(self)
        self.stdout = DummySubprocess.stdout

    def __init__(self, cmdline, *args, dry_run=False, **kwargs):
        logging.debug("$ %s", cmdline)
        if dry_run:
            # that'll be funny :)
            self.skip_init()
        else:
            super().__init__(cmdline, *args, **kwargs)

class ReinjectWrapper(TaskHandle):
    def __init__(self, task_handle, reinject_callback, directory):
        super().__init__()
        self.hnd = task_handle
        self.reinject_callback = reinject_callback
        self.directory = directory

    def _handle_result(self):
        if result == 0 and self.reinject_callback is not None:
            self.reinject_callback(self.directory)
            self.reinject_callback = None
            del self.directory

    def poll(self):
        result = self.hnd.poll()
        self._handle_result(result)
        return result

    def wait(self):
        result = self.hnd.wait()
        self._handle_result(result)
        return result

class EncoderHandle(SubprocessHandle):
    def __init__(self, *args, weight=0, **kwargs):
        self.weight = weight
        super().__init__(*args, **kwargs)

    @staticmethod
    def _ensure_output_file(flac_file, output_directory, extension):
        new_name = "./" + os.path.splitext(flac_file)[0] + "." + extension
        out_file = os.path.join(output_directory, new_name)
        out_dir = os.path.dirname(out_file)
        if not os.path.isdir(out_dir):
            os.makedirs(out_dir)
        return out_file

    @staticmethod
    def _get_flac_decoder(flac_file, **kwargs):
        in_pipe_process = SubprocessHandle(
            [
                "flac",
                "-dc",
                flac_file
            ],
            stdin=None,
            stdout=subprocess.PIPE,
            stderr=devnull,
            **kwargs
        )
        return in_pipe_process

class PipeEncoderHandle(EncoderHandle):
    class OutFileToken:
        __init__ = None

    @staticmethod
    def replace_token(token, substitute):
        def replacer(item):
            return substitute if item is token else item
        return replacer

    def __init__(self,
            flac_file,
            command_template,
            output_directory,
            suffix,
            skip_existing=False,
            weight=0,
            **kwargs):

        out_file = self._ensure_output_file(flac_file, output_directory, suffix)
        if os.path.isfile(out_file) and skip_existing:
            logging.info("skipping existing file: %s", out_file)
            self.skip_init()
            self.weight = 0
            return

        command = list(map(
            self.replace_token(self.OutFileToken, out_file),
            command_template))

        in_pipe = self._get_flac_decoder(flac_file, **kwargs)
        try:
            super().__init__(
                command,
                stdin=in_pipe.stdout,
                stdout=devnull,
                weight=weight,
                **kwargs)
        except:
            in_pipe.kill()
            raise
        self.in_pipe = in_pipe
        self.out_file = out_file

    def term(self):
        if not self.weight:
            return
        logging.info("terminating transcoder for %s", self.out_file)
        self.in_pipe.term()
        super().term()
        os.unlink(self.out_file)

    def kill(self):
        if not self.weight:
            return
        logging.info("killing transcoder for %s", self.out_file)
        self.in_pipe.kill()
        super().kill()
        os.unlink(self.out_file)

class OpusEncoderHandle(PipeEncoderHandle):
    def __init__(self, flac_file, comments, output_directory, mode,
            skip_existing=False,
            weight=0,
            complexity=10,
            bitrate=None,
            **kwargs):
        comment_list = []
        for key, value in comments.items():
            comment_list.append("--comment")
            comment_list.append("{0}={1}".format(key, value))

        command_template = ["opusenc"]
        if bitrate is not None:
            command_template.append("--bitrate")
            command_template.append("{.1f}".format(bitrate))
        command_template.extend(mode.to_args())
        command_template.extend(comment_list)
        command_template.append("-")
        command_template.append(self.OutFileToken)

        super().__init__(
            flac_file, command_template, output_directory, "opus",
            skip_existing=skip_existing, weight=weight, **kwargs)

class VorbisEncoderHandle(PipeEncoderHandle):
    def __init__(self, flac_file, comments, output_directory, mode,
            skip_existing=False,
            weight=0,
            **kwargs):
        comment_list = []
        for key, value in comments.items():
            comment_list.append("--comment={0}={1}".format(key, value))

        command_template = ["oggenc"]
        command_template.extend(mode.to_args())
        command_template.append("--utf8")
        command_template.extend(comment_list)
        command_template.append("-Q")
        command_template.append("-")
        command_template.append("-o")
        command_template.append(self.OutFileToken)

        super().__init__(
            flac_file, command_template, output_directory, "ogg",
            skip_existing=skip_existing, weight=weight, **kwargs)

class Task(metaclass=abc.ABCMeta):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self._args = args
        self._kwargs = kwargs

    @abc.abstractmethod
    def __call__(self):
        """
        Return a task handle executing the task represented by this instance.
        """

class DirectoryFilter(Task):
    def __init__(self, directory, reinject_callback=None):
        super().__init__()
        self.directory = directory
        self.reinject_callback = reinject_callback

class Encoder(Task, metaclass=abc.ABCMeta):
    comment_re = re.compile("^\s*comment\[[0-9]+\]: ([^=]+)=(.+)$")

    def __init__(self, flac_file, output_directory, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.output_directory = output_directory
        self.flac_file = flac_file
        self.weight = os.stat(flac_file).st_size

    @abc.abstractclassmethod
    def _get_encoder_handle_class(cls):
        pass

    @abc.abstractclassmethod
    def _get_encoder_mnemonic(cls):
        pass

    def _get_metadata(self):
        output = subprocess.check_output([
            "metaflac",
            "--list",
            "--block-type", "VORBIS_COMMENT",
            self.flac_file
        ]).decode().split("\n")

        comment_re = self.comment_re
        comments = {}
        for line in output:
            m = comment_re.match(line)
            if m:
                g = m.groups()
                comments[g[0]] = g[1]
        return comments

    def __call__(self):
        comments = self._get_metadata()
        return self._get_encoder_handle_class()(
            self.flac_file,
            comments,
            self.output_directory,
            *self._args,
            weight=self.weight,
            **self._kwargs
        )

    def __repr__(self):
        return "<encode {!r} to {}>".format(
            self.flac_file,
            self._get_encoder_mnemonic())

class OpusEncoder(Encoder):
    class Mode:
        __init__ = None

        class _Bitrate:
            def __init__(self, bitrate=None):
                self._bitrate = bitrate

            def _to_args(self):
                if self._bitrate is not None:
                    return ["--bitrate", "{:.1f}".format(self._bitrate)]
                else:
                    return []

        class VBR(_Bitrate):
            def to_args(self):
                return super()._to_args() + ["--vbr"]

        class cVBR(_Bitrate):
            def to_args(self):
                return super()._to_args() + ["--cvbr"]

    def __init__(self, flac_file, output_directory,
            mode=Mode.VBR(128),
            **kwargs):
        super().__init__(flac_file, output_directory, mode, **kwargs)

    @classmethod
    def _get_encoder_handle_class(cls):
        return OpusEncoderHandle

    @classmethod
    def _get_encoder_mnemonic(cls):
        return "opus"

class VorbisEncoder(Encoder):
    class Mode:
        __init__ = None

        class Bitrate:
            def __init__(self, bitrate, managed=False):
                self._bitrate = int(bitrate)
                self._managed = managed

            def to_args(self):
                result = ["--bitrate", "{:d}".format(self._bitrate)]
                if self._managed:
                    result.append("--managed")
                return result

        class Quality:
            def __init__(self, quality):
                self._quality = quality

            def to_args(self):
                return ["-q", "{:.2f}".format(self._quality)]

    def __init__(self, flac_file, output_directory,
            mode=Mode.Quality(6),
            **kwargs):
        super().__init__(flac_file, output_directory, mode, **kwargs)

    @classmethod
    def _get_encoder_handle_class(cls):
        return VorbisEncoderHandle

    @classmethod
    def _get_encoder_mnemonic(cls):
        return "oggvorbis"

encoders = {
    "opus": OpusEncoder,
    "vorbis": VorbisEncoder,
    "ogg": VorbisEncoder,
    "ogg+vorbis": VorbisEncoder
}

dir_filters = {
#    "replay-gain", ReplayGain
}

class Scheduler:
    def __init__(self, parallel_tasks):
        self.pending_tasks = []
        self.running_tasks = []
        self.max_tasks = parallel_tasks
        self.started_at = time.time()
        self.tasks_completed = 0
        self.total_weight = 0
        self.done_weight = 0

    def graceful_termination(self):
        logging.info("sending all tasks a termination signal")
        for task in self.running_tasks:
            task.term()
        self.running_tasks = []
        self.pending_tasks = []
        logging.info("all tasks terminated -- work queue cleared")

    def poll(self):
        changed = False
        for task in list(self.running_tasks):
            returncode = task.poll()
            if returncode is not None:
                self.tasks_completed += 1
                self.done_weight += task.weight
                self.running_tasks.remove(task)
                if returncode == 0:
                    changed = True
                else:
                    logger.error("task %r returned a nonzero status code: %s", task, returncode)

        while len(self.running_tasks) < self.max_tasks and \
                len(self.pending_tasks) > 0:
            new_task = self.pending_tasks.pop()
            try:
                handle = new_task()
            except Exception as err:
                logger.error("while trying to start next task:")
                logger.exception(err)
                continue
            self.total_weight -= new_task.weight
            del new_task
            self.total_weight += handle.weight
            self.running_tasks.append(handle)
            changed = True

        if changed:
            logger.info("%d tasks pending; %d tasks running", len(self.pending_tasks), len(self.running_tasks))

        return len(self.running_tasks) > 0 or len(self.pending_tasks) > 0

    def schedule(self, task):
        logging.debug("enqueued task %r", task)
        self.pending_tasks.append(task)
        self.total_weight += task.weight
        logging.debug("new weight %d", self.total_weight)

    def schedule_tasks(self, iterable):
        for task in iterable:
            self.schedule(task)

    def guesstimate(self):
        curr_time = time.time()
        delta = curr_time - self.started_at
        done = self.tasks_completed
        pending = len(self.pending_tasks)
        running = len(self.running_tasks)
        if self.tasks_completed < 10 or self.done_weight == 0:
            eta = None
        else:
            rate = self.done_weight / delta
            eta = (self.total_weight - self.done_weight) / rate
        return done, pending, running, eta

def task_generator(transcoders, **kwargs):
    def generator(filepath):
        for transcoder_cls, output_dir in transcoders:
            yield transcoder_cls(filepath, output_dir, **kwargs)
    return generator

def scan_dir(directory, heartbeat, task_generator):
    if not os.path.isdir(directory):
        logging.error("Not a directory: %s", directory)
        heartbeat()
        return
    for dirpath, dirnames, filenames in os.walk(directory):
        for filename in filenames:
            if os.path.splitext(filename)[1] != ".flac":
                logging.debug("skipping non-flac file: %s", filename)
                continue

            logging.debug("adding tasks for: %s", filename)
            filepath = os.path.join(dirpath, filename)
            for task in task_generator(filepath):
                yield task
        heartbeat()

def format_time(dt):
    if dt > 120:
        minutes = round(dt / 60)
        if minutes >= 60:
            hours = int(minutes / 60)
            minutes %= 60
            return "{}h {}min".format(hours, minutes)
        else:
            return "{}min".format(minutes)
    else:
        return "{:0f}s".format(dt)

if __name__ == "__main__":
    import argparse
    import sys

    def positive_integer(x):
        x = int(x)
        if x <= 0:
            raise ValueError("Must be a positive integer number.")
        return x

    class ValidateTranscoders(argparse.Action):
        def __call__(self, parser, namespace, values, option_string=None):
            transcoder, output_dir = values
            try:
                transcoder_class = encoders[transcoder]
            except KeyError:
                raise argparse.ArgumentError(
                        self, "invalid choice: '{value}' (choose from {encoders})".format(
                            value=values[0],
                            encoders=", ".join("'%s'" % (x) for x in encoders.keys())
                    ))
            namespace.transcoders.append((transcoder_class, output_dir))
            setattr(namespace, self.dest, namespace.transcoders)

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-x", "--transcode",
        metavar=('ENCODER', 'OUTPUT_DIR'),
        action=ValidateTranscoders,
        nargs=2,
        default=[],
        help="Encoder to apply to the flac files. Can be specified multiple times to apply multiple encoders. At least one transcoder must be given.",
        dest="transcoders"
    )
    parser.add_argument(
        "-j", "--parallel",
        metavar="COUNT",
        type=positive_integer,
        help="Maximum number of tasks to run in parallel (default 1)",
        default=1,
        dest="parallel_tasks"
    )
    parser.add_argument(
        "-d", "--dry-run",
        action="store_true",
        default=False,
        help="Do not execute anything, but print what would be done (requires -vvv to see anything)",
        dest="dry_run"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (anything beyond -vvv doesn't make sense)",
        dest="verbosity"
    )
    parser.add_argument(
        "-s", "--skip-existing",
        default=False,
        action="store_true",
        help="If set, existing destination files will cause a skip",
    )
    parser.add_argument(
        "-p", "--progress",
        default=0,
        action="store_const",
        const=1,
        help="Show progress on terminal"
    )
    parser.add_argument(
        "dir",
        nargs="+",
        help="Directory to scan for flac files. Note that paths are relevant."
    )

    args = parser.parse_args()

    if len(args.transcoders) == 0:
        parser.print_help()
        print("It's not reasonable to run this script without a single transcoder enabled.")
        sys.exit(1)

    logging.basicConfig(level=logging.ERROR, format='{0}:%(levelname)-8s %(message)s'.format(os.path.basename(sys.argv[0])))
    if args.verbosity >= 3:
        logger.setLevel(logging.DEBUG)
    elif args.verbosity >= 2:
        logger.setLevel(logging.INFO)
    elif args.verbosity >= 1:
        logger.setLevel(logging.WARNING)

    task_generator = task_generator(
        args.transcoders,
        dry_run=args.dry_run,
        skip_existing=args.skip_existing
    )
    scheduler = Scheduler(args.parallel_tasks)
    try:
        for directory in args.dir:
            scheduler.schedule_tasks(scan_dir(directory, scheduler.poll, task_generator))

        i = 0
        incr = args.progress
        while scheduler.poll():
            i += incr
            time.sleep(0.01)
            if i >= 20:
                i = 0
                estimate = scheduler.guesstimate()
                done, pending, running, eta = estimate
                etastr = "guessing" if eta is None else format_time(eta)
                print(
                    "{:6.2f}% {:6d} done, {:6d} pending, {:2d} running, ETA {}{:20s}".format(
                        100*done / (done+pending), done, pending, running, etastr, ""
                    ),
                    end="\r"
                )
    except KeyboardInterrupt:
        if args.progress:
            print()
        print("SIGINT received -- terminating")
        scheduler.graceful_termination()
    except:
        scheduler.graceful_termination()
        raise

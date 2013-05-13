#!/usr/bin/python3
# File name: tool.py
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

import sys
import os
import os.path
import subprocess
from argparse import ArgumentParser
import time
import re
import logging

devnull = open('/dev/null', 'w')

class JobDescription:
    def __init__(self, commandLine, asShell, callbackOnDone):
        self.commandLine = commandLine
        self.asShell = asShell
        self.callbackOnDone = callbackOnDone

    def fork(self):
        return subprocess.Popen(self.commandLine, shell=self.asShell, stdin=None, stdout=devnull, stderr=devnull)

class OpusJob:
    def __init__(self, sourceFile, opusCall, callbackOnDone):
        self.sourceFile = sourceFile
        self.opusCall = opusCall
        self.callbackOnDone = callbackOnDone

    def fork(self):
        flacdec_out = subprocess.Popen(["flac", "-dc", self.sourceFile], stdin=None, stdout=subprocess.PIPE, stderr=devnull)
        return subprocess.Popen(self.opusCall, stdin=flacdec_out.stdout, stdout=devnull, stderr=devnull)

class Subprocess:
    def __init__(self):
        self.ready = True
        self.instance = None
        self.callbackOnDone = None

    def assign(self, description):
        if not self.ready:
            raise Exception("Attempt to assign a command to a busy subprocess.")
        self.instance = description.fork()
        self.ready = False
        self.callbackOnDone = description.callbackOnDone

    def poll(self):
        if self.instance is None:
            self.ready = True
            return
        if self.instance.poll() is not None:
            self.ready = True
            #print("Done: %s" % (' '.join(self.commandLine)))
            if self.callbackOnDone is not None:
                self.callbackOnDone()
            self.instance = None
        else:
            self.ready = False

class SubprocessManager:
    def __init__(self):
        self.processes = []
        self.idles = []
        self.pending = []

    def addSlot(self):
        process = Subprocess()
        self.processes.append(process)
        self.idles.append(process)

    def poll(self):
        changed = False
        for process in self.processes:
            process.poll()
            if process.ready and not (process in self.idles):
                self.idles.append(process)
        while len(self.pending) > 0 and len(self.idles) > 0:
            idle = self.idles.pop()
            idle.assign(self.pending.pop(0))
            changed = True
        if changed:
            print("tool.py: %d jobs unassigned, %d running" % (len(self.pending), len(self.processes) - len(self.idles)))
        return changed

    def addJob(self, description):
        self.pending.append(description)

    def busy(self):
        return len(self.pending) > 0 or len(self.idles) < len(self.processes)

class FileJob:
    def getJobForFile(self, fileName, callback=None):
        return None

class FileJobOpusTranscode(FileJob):
    def getJobForFile(self, fileName, callback=None):
        output = subprocess.check_output(["metaflac", "--list", "--block-type", "VORBIS_COMMENT", fileName]).decode().split("\n")
        commentRe = re.compile("^\s*comment\[[0-9]+\]: ([^=]+)=(.+)$")
        commentDict = {}
        for line in output:
            m = commentRe.match(line)
            if m:
                g = m.groups()
                commentDict[g[0]] = g[1]

        arguments = ["opusenc", "--music"]
        for key, value in commentDict.items():
            arguments.append("--comment")
            arguments.append("{0}={1}".format(key, value))
        arguments.append("-")
        outFile = os.path.join("/home/horazont/Opus-Music", fileName[:-len(".flac")]) + ".opus"
        outDir = os.path.dirname(outFile)
        if not os.path.isdir(outDir):
            os.makedirs(outDir)
        arguments.append(outFile)

        return OpusJob(fileName, arguments, callback)


class FileJobLQTranscode(FileJob):
    def getJobForFile(self, fileName, callback=None):
        return JobDescription(['/home/horazont/Music/transcode-helper.sh', fileName], False, callback)

class FileJobXLQTranscode(FileJob):
    def getJobForFile(self, fileName, callback=None):
        return JobDescription(['/home/horazont/Music/xlq-transcode-helper.sh', fileName], False, callback)

class MultiFileJob:
    def getJobForFiles(self, fileList, callback=None):
        return None

class MultiFileJobReplayGain(MultiFileJob):
    def getJobForFiles(self, fileList, callback=None):
        return JobDescription(['metaflac', '--add-replay-gain'] + fileList, False, callback)

class FinishCallback:
    def __init__(self, fileList, tool):
        self.fileList = fileList
        self.tool = tool

    def __call__(self):
        for file in self.fileList:
            self.tool.addEncoderJobs(file)

class Tool:
    @staticmethod
    def SubprocessCount(value):
        v = int(value)
        if v <= 0:
            raise ValueError("Must have at least one subprocess.")
        return v

    def __init__(self):
        self.subs = SubprocessManager()
        self.fileJobs = []
        self.multiJobs = []
        self.parseArgs()
        self.run()

    def parseArgs(self):
        parser = ArgumentParser()
        parser.add_argument(
            "-l",
            "--lq",
            help="Enable conversion to LQ",
            action="store_true",
            dest="transcodeLQ"
        )
        parser.add_argument(
            "-x",
            "--xlq",
            help="Enable conversion to XLQ",
            action="store_true",
            dest="transcodeXLQ"
        )
        parser.add_argument(
            "-o",
            "--opus",
            help="Enable conversion to Opus",
            action="store_true",
            dest="transcodeOpus"
        )
        parser.add_argument(
            "-r",
            "--replay-gain",
            help="Apply replay gain (using metaflac)",
            action="store_true",
            dest="applyReplayGain"
        )
        parser.add_argument(
            "-j",
            help="How many subprocesses to fork at a max",
            type=self.SubprocessCount,
            metavar="COUNT",
            dest="subprocessCount",
            default=1
        )
        parser.add_argument(
            "dirs",
            nargs="+",
            help="Directory in which to look for music files (recurses)",
            metavar="DIR"
        )
        self.args = parser.parse_args()
        self.dirs = self.args.dirs
        for i in range(0, self.args.subprocessCount):
            self.subs.addSlot()

        if self.args.transcodeOpus:
            self.fileJobs.append(FileJobOpusTranscode())
        if self.args.transcodeLQ:
            self.fileJobs.append(FileJobLQTranscode())
        if self.args.transcodeXLQ:
            self.fileJobs.append(FileJobXLQTranscode())
        if self.args.applyReplayGain:
            self.multiJobs.append(MultiFileJobReplayGain())

        if len(self.fileJobs) + len(self.multiJobs) == 0:
            print("No jobs specified—nothing to do.")
            sys.exit(0)
        self.hasMultiJobs = len(self.multiJobs) > 0

    def addEncoderJobs(self, filePath):
        for encoder in self.fileJobs:
            self.subs.addJob(encoder.getJobForFile(filePath))

    def addMultiJobs(self, fileList, callback):
        for multiJob in self.multiJobs:
            self.subs.addJob(multiJob.getJobForFiles(fileList, callback=callback))

    def runOnDir(self, path):
        files = []
        for node in os.listdir(path):
            self.subs.poll()
            nodePath = path + '/' + node
            if os.path.isdir(nodePath):
                self.runOnDir(nodePath)
            elif os.path.isfile(nodePath) and (os.path.splitext(node)[1] == '.flac'):
                if not self.hasMultiJobs:
                    self.addEncoderJobs(nodePath)
                else:
                    files.append(nodePath)
        if len(files) > 0:
            self.addMultiJobs(files, FinishCallback(files, self))

    def runRootOnDir(self, paths):
        notChangedCount = 0
        for path in paths:
            if not os.path.isdir(path):
                sys.stderr.write("%s: Not a directory" % (path))
                sys.stderr.flush()
                return
            self.runOnDir(path)
        while self.subs.busy():
            if not self.subs.poll():
                notChangedCount += 1
                time.sleep(notChangedCount * 0.05)
            else:
                notChangedCount = 0

    def run(self):
        self.runRootOnDir(self.dirs)

tool = Tool()

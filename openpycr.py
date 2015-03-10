#!/usr/bin/env python3
import curses
import time
import sys
import argparse
from openpcrlib import OpenPCR
import PCRCompiler

class CursesDisplay():
    def __init__(self, screen, dev):
        self.scr = screen
        self.dev = dev

    def monitor(self):
        self.scr.nodelay(1) # Make self.scr.getch nonblocking.
        while True:
            self.printStatusMsg()
            time.sleep(1)
            char = self.scr.getch()
            if char != -1:
                break
            S = self.dev.readstatus()
            if S['state'] == 'complete':
                break
                break

    def writeln(self,string):
        self.scr.erase() # Clear window
        self.scr.addstr(0,0,string)
        self.scr.refresh()

    def printStatusMsg(self):
        S = self.dev.readstatus()
        try:
            PrettyStatus = 'Welcome to the OpenPyCR Real-time Monitor.\n'
            PrettyStatus += 'Current Program: {0}\n'.format(S['program'])
            PrettyStatus += ' Step "{0}" of cycle {1}\n'.format(S['currentstep'],str(S['cycle']))
            PrettyStatus += ' Currently: {0}\n'.format(S['job'])
            PrettyStatus += ' Block: {0}C, Lid: {1}C\n'.format(str(S['blocktemp']),str(S['lidtemp']))
            PrettyStatus += ' Remaining Time: {0}\n(Press any key to exit monitor mode)'.format(S['timeleft'])
        except KeyError:
            PrettyStatus = 'Run Finished.\n(Press any key to exit monitor mode)'
        self.writeln(PrettyStatus)

def CursesMonitor(dev):
    stdscr = curses.initscr()
    curses.cbreak()
    Console = CursesDisplay(stdscr, dev)
    Console.monitor()
    curses.nocbreak()
    curses.endwin()

#======= Functions for Terminal Use Follow ========
def status(device, args):
    device.printstatus()

def monitor(device, args):
    CursesMonitor(device)

def send(device, args):
    with args.program_file as InF:
        program = InF.read().strip()
    program = PCRCompiler.parse_program(program)
    device.sendprogram(program)

def stop(device, args):
    device.stop()
    
def log(device, args):
    # args.interval and args.output_file
    with args.output_file as LogF:
        lastflush = time.time()
        try:
            while True:
                LogLine = device.csvstatus(args.columns)
                if device.active:
                    LogF.write(LogLine+"\n")
                else:
                    break
                if lastflush >= args.flush_interval:
                    lastflush = time.time()
                    LogF.flush()
                time.sleep(args.interval)
        except KeyboardInterrupt:
            pass

def pcrcompile(device, args):
    with args.program_file as InF:
        print(PCRCompiler.parse_program(InF.read()))

P = argparse.ArgumentParser(
                description = "OpenPyCR: A pure-python controller and monitor for the OpenPCR Thermal Cycler.",
                epilog = "by Cathal Garvey, copyright 2013, released as Free Software under the GNU AGPL v3 or later.")
P.add_argument("-m","--device-mountpoint",default="/media/OPENPCR",type=str,
                    help="Path of the OpenPCR device. On Debian GNU/Linux (incl. Ubuntu) the default is usually correct.")
Subs = P.add_subparsers(help="Subcommands: Try calling '-h' or '--help' after these to get more specific help, if available.")

P_status = Subs.add_parser('status',help="Print a oen-time status message.")
P_status.set_defaults(function = status)

P_monitor = Subs.add_parser('monitor',help="Open a curses monitor for OpenPCR device.")
P_monitor.set_defaults(function = monitor)

P_send = Subs.add_parser('send',help="Send a string or file as a program to the OpenPCR device.")
P_send.add_argument("-p","--program-file",type=argparse.FileType("r"),default=sys.stdin,
                        help="Program to send. If not specified, reads from standard input.")
P_send.set_defaults(function = send)

P_stop = Subs.add_parser('stop',help='Send the stop signal to the OpenPCR to terminate current program.')
P_stop.set_defaults(function = stop)

P_log = Subs.add_parser('log',help='Print (or append to file) status information in csv format at set intervals.')
P_log.set_defaults(function = log)
P_log.add_argument("-i","--interval",type=int,default=5,help="Interval in seconds between log entries.")
P_log.add_argument("-o","--output-file",type=argparse.FileType("a"),default=sys.stdout,
                        help="File to append log output to. Default is stdout; print to terminal.")
P_log.add_argument("--columns",nargs="+",type=str,default=['currenttime','elapsedsecs','cycle','blocktemp'],
                        help="Columns to print to log. Options are: state job blocktemp lidtemp elapsedsecs secsleft currentstep cycle program nonce minsleft hoursleft timeleft currenttime")
P_log.add_argument("--flush-interval",type=int,default=30,
                        help="Interval by which to flush outut stream; may help prevent data loss on crash. If unsure, leave alone.")

P_compile = Subs.add_parser('compile',help="Compile a program in OpenPyCR format to the lower-level OpenPCR format.")
P_compile.set_defaults(function=pcrcompile)
P_compile.add_argument("-p","--program-file",type=argparse.FileType("r"),default=sys.stdin,
                        help="Program to send. If not specified, reads from standard input.")

# Parse arguments, and pass arguments into the associated function for handling
# according to appropriate subcommand.
A = P.parse_args()
Dev = OpenPCR(devicepath = A.device_mountpoint)
if not hasattr(A,"function"):
    P.print_usage()
else:
    A.function(Dev, A)

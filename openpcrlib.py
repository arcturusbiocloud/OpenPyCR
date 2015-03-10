import time
import sys
import os
import collections

if "linux" not in sys.platform:
    print("OpenPyCR uses system calls that are only available on Linux platforms. Your platform -",
            sys.platform,"- is probably incompatible, so reading OpenPCR status is probably impossible and this",
            "program will probably crash. This is *not a bug* if you are using a platform other",
            "than linux, and there is no plan to support non-free/libre platforms.", file=sys.stderr)
if sys.version_info[:2] < (3,3):
    # native posix_fadvise introduced in 3.3, can shim in with ctypes:
    import ctypes
    try:
        os.POSIX_FADV_NORMAL     = 0
        os.POSIX_FADV_RANDOM     = 1
        os.POSIX_FADV_SEQUENTIAL = 2
        os.POSIX_FADV_WILLNEED   = 3
        os.POSIX_FADV_DONTNEED   = 4
        os.POSIX_FADV_NOREUSE    = 5
        # The above will (or should?) always work, so do that first.
        libc = ctypes.CDLL("libc.so.6")
        os.posix_fadvise = libc.posix_fadvise
    except OSError:
        print("Attempted to open libc.so.6 to import the posix_fadvise system call failed.",
              "Reading from OpenPCR will not function correctly as disk/os level caching will interfere.",file=sys.stderr)
        # Add an empty shim so it doesn't crash later.
        if not hasattr(os, "posix_fadvise"): os.posix_fadvise = lambda w,x,y,a:None

class OpenPCRError(Exception):
    pass

class OpenPCR:
    def __init__(self,devicepath=''):
        self.devicepath = devicepath or '/media/OPENPCR/'
        self.active = False

    @property
    def ready(self):
        return os.path.exists(self.devicepath) and os.path.exists(os.path.join(self.devicepath,"STATUS.TXT"))
        
    def sendprogram(self, program, status_callback=lambda x:None):
        '''Sends a program to the OpenPCR and prints a verification if successful.
        This can optionally send status messages (as a single string arg) to a callback.'''
        if not self.ready:
            raise OpenPCRError("Cannot send program as device is not ready.")
	
        NewNonce = 0
        # OrderedDict preserves key order; may be critical for leading 's=ACGTC' signal.
        dissectedprogram = collections.OrderedDict([x.split("=",1) for x in program.split("&")])
        dissectedprogram['d'] = str(NewNonce)
        self._sendprogram('&'.join(['='.join([x,y]) for x,y in dissectedprogram.items()]))

        # Wait 2s to let OpenPCR recover from sending program, 
        # then further 5s for program update.
        status_callback("Waiting for two seconds for OpenPCR to resume responding.")
        Status = time.sleep(2) # Now Status == None, not undefined.
        started_waiting = time.time()
        while time.time() - started_waiting < 5:
            try:
                Status = self.readstatus()
                break
            except ValueError:
                status_callback("Still waiting for OpenPCR to respond..")
                time.sleep(0.5)
        else:
            status_callback("Device failed to respond to status queries after sending updated program.")
            raise OpenPCRError("Device failed to respond to status queries after sending updated program.")
        # Printouts are nice and all but silent success and angry fail are more
        # useful for building other applications on top of this.
        if Status and Status['nonce'] == NewNonce:
            status_callback("Program successfully sent.")
        else:
            status_callback("Program sent to device but device does not report receipt.")
            raise OpenPCRError("Program sent to device but device does not report receipt.")

    def _sendprogram(self,program):
        with open(os.path.join(self.devicepath,'CONTROL.TXT'), mode='w') as Fout:
            Fout.write(program)

    def test(self):
        # Expand here; this should test sending, sequential status reads, and stopping.
        self.sendprogram('s=ACGTC&c=start&n=OpenPyCR Test Program&p=(20[10|45|TestStep1][20|25|TestStep2])')

    def stop(self):
        self.sendprogram('s=ACGTC&c=stop')

    def ncc(self):
        '''Low-level. Calls ncc binary for appropriate platform, returns raw output as string.
        Behaves like "no-cache-cat" (ncc) but in pure-python. Only works on Unix, possibly Linux.
        If this does not work correctly it is a silent failure; self-testing is essential
        to ensure that non-caching reads are executed successfully. If not, fallback to
        custom compiled C binaries would be necessary to get readouts.'''
        if not self.ready:
            raise OpenPCRError("Device not ready, cannot read status.")
        filen = os.path.join(self.devicepath,'STATUS.TXT')
        with open(filen,"rb") as InF:
            os.posix_fadvise(InF.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
            fc = InF.read()
        # Return until first null character.
        # Odd null/whitespace pattern is incompatible with unicode mode.
        return fc.split(b"\0",1)[0].decode()

    def readstatus(self):
        'Calls ncc and translates output into a dictionary of values.'
        statustxt = self.ncc()
        status = dict([x.split("=") for x in statustxt.split("&")])
        statusd = {'state': status.get('s','Unknown'),
                   'job': status.get('t','Unknown'),
                   'blocktemp': float(status.get('b',0)),
                   'lidtemp': float(status.get('l',0)),
                   'elapsedsecs': int(status.get('e',0)),
                   'secsleft': int(status.get('r',0)),
                   'currentstep': status.get('p','Unknown'),
                   'cycle': int(status.get('c',0)),
                   'program': status.get('n','Unknown'),
                   'nonce': int(status.get('d',-1)),
                   }
        self.active = False if statusd['state'] in ['Complete','Inactive'] else True
        if statusd['nonce'] == -1:
            raise IOError("Received no program-identifier number from device - failure to communicate/reprogram?") 
        # Now to clean up TIME ITSELF
        statusd['minsleft'] = statusd['secsleft'] // 60
        statusd['hoursleft'] = statusd['minsleft'] // 60
        extramins = statusd['minsleft'] - (statusd['hoursleft'] * 60)
        extrasecs = statusd['secsleft'] - (statusd['minsleft'] * 60)
        statusd['timeleft'] = '{0}:{1}:{2}'.format(statusd['hoursleft'], extramins, extrasecs)
        statusd['currenttime'] = time.strftime("%H:%M:%S",time.localtime())
        return statusd

    def csvstatus(self,keyorder = ['currenttime','elapsedsecs','cycle','blocktemp']):
        '''Calls readstatus and formats output for logging to csv.

        keyorder is a list of dictionary keys to use, in desired order, when
        formatting output. The default provides the elapsed time in seconds,
        current cycle number, and temperature of the block.'''
        # Assemble keyworded formatting string from keyorder argument, then
        # unpack the dictionary result of self.readstatus into it to get return.
        return ', '.join(['{'+k+'}' for k in keyorder]).format(**self.readstatus())

    def printstatus(self):
        'Calls readstatus and prints useful information to stdout.'
        S = self.readstatus()
        if S['state'] == 'complete':  print("Program complete.")
        elif S['state'] == 'stopped': print("System idle. No program running.")
        elif S['state'] == "Unknown": print("System state unknown.")
        else:
            print(('Current Program: {program}\n'
                   "Step '{currentstep}' of cycle {cycle}\n"
                   "Currently: {job}\n"
                   "Block: {blocktemp}°C, Lid: {lidtemp}°C\n"
                   "Remaining Time: {timeleft}").format(**S))
   

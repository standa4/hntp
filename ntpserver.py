#!/usr/bin/env python

import datetime
import socket
import struct
import time
import base64
import Queue
import mutex
import threading
import select
import datetime
import ConfigParser
import json



import logging
logging.basicConfig()
logger = logging.getLogger('hpfeed')
hdlr = logging.FileHandler('/var/tmp/hpfeed-ntp.log')
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
hdlr.setFormatter(formatter)
logger.addHandler(hdlr)
logger.setLevel(logging.INFO)



taskQueue = Queue.Queue()
stopFlag = False

config = ConfigParser.RawConfigParser()
config.read("honeyntp.conf")

import syslog
syslog.openlog('HONEYNTP', syslog.LOG_PID, syslog.LOG_USER)

# listen address and port
listenIp = config.get('global','listen')
listenPort = int(config.get('global','port'))

hpc = None
gd = None
rediscl = None

# determine if hpfeeds is used
LogToHpfeeds = False

if config.has_section('log_hpfeed'):
    import hpfeeds
    import pygeoip
    LogToHpfeeds = True
    hpf_host = config.get('log_hpfeed', 'host')
    hpf_port = int(config.get('log_hpfeed', 'port'))
    hpf_CHANNELS= []
    hpf_CHANNELS.append(config.get('log_hpfeed', 'channel'))
    hpf_IDENT = config.get('log_hpfeed', 'ident')
    hpf_SECRET = config.get('log_hpfeed', 'secret')
    hpc = hpfeeds.new(hpf_host, hpf_port, hpf_IDENT, hpf_SECRET)
    gd  = pygeoip.GeoIP('GeoLiteCity.dat')

    logger.info("Connected to %s" % hpc.brokername)


# determine if log to redis db
LogToRedis = False

if config.has_section('log_redis'):
    import redis
    LogToRedis = True
    redis_db = int(config.get('log_redis','redis_db'))
    redis_host = config.get('log_redis','redis_host')
    redis_port = int(config.get('log_redis','redis_port'))
    rediscl = redis.Redis(host = redis_host, port = redis_port, db = redis_db)



def log(source, port, info="NTP scan"):
    source = filter(lambda c: c.isalnum() or c == '.' or c == '/', source)

    timestamp = int(int(time.time()))

    msg = "%s: %s:%s - %s" % (info,source,port, datetime.datetime.now())
    print msg
    logger.info("msg: %s" % msg)

    if LogToRedis:
        skey = "B:%s:%s" % (source, port)
        lkey = "E:%s:%s" % (source, port)
        rediscl.set(lkey, timestamp)
        if not rediscl.exists(skey):
            rediscl.set(skey, timestamp)

    if LogToHpfeeds:
        d = gd.record_by_addr(source)
        if d == None:
            d = {"latitude":25.03, "logitude": 121.53, "country_code": "TW"}
        dat = {}
        dat["latitude"] = d["latitude"]
        dat["longitude"] = d["longitude"]
        dat["type"] = "%s: %s" % (source, msg)
        dat["countrycode"] = d["country_code"]
        dat["city"] = d["city"]
        fmsg = json.dumps(dat)
        hpc.publish(hpf_CHANNELS, fmsg)




def system_to_ntp_time(timestamp):
    """Convert a system time to a NTP time.

    Parameters:
    timestamp -- timestamp in system time

    Returns:
    corresponding NTP time
    """
    return timestamp + NTP.NTP_DELTA

def _to_int(timestamp):
    """Return the integral part of a timestamp.

    Parameters:
    timestamp -- NTP timestamp

    Retuns:
    integral part
    """
    return int(timestamp)

def _to_frac(timestamp, n=32):
    """Return the fractional part of a timestamp.

    Parameters:
    timestamp -- NTP timestamp
    n         -- number of bits of the fractional part

    Retuns:
    fractional part
    """
    return int(abs(timestamp - _to_int(timestamp)) * 2**n)

def _to_time(integ, frac, n=32):
    """Return a timestamp from an integral and fractional part.

    Parameters:
    integ -- integral part
    frac  -- fractional part
    n     -- number of bits of the fractional part

    Retuns:
    timestamp
    """
    return integ + float(frac)/2**n



class NTPException(Exception):
    """Exception raised by this module."""
    pass


class NTP:
    """Helper class defining constants."""

    _SYSTEM_EPOCH = datetime.date(*time.gmtime(0)[0:3])
    """system epoch"""
    _NTP_EPOCH = datetime.date(1900, 1, 1)
    """NTP epoch"""
    NTP_DELTA = (_SYSTEM_EPOCH - _NTP_EPOCH).days * 24 * 3600
    """delta between system and NTP time"""

    REF_ID_TABLE = {
            'DNC': "DNC routing protocol",
            'NIST': "NIST public modem",
            'TSP': "TSP time protocol",
            'DTS': "Digital Time Service",
            'ATOM': "Atomic clock (calibrated)",
            'VLF': "VLF radio (OMEGA, etc)",
            'callsign': "Generic radio",
            'LORC': "LORAN-C radionavidation",
            'GOES': "GOES UHF environment satellite",
            'GPS': "GPS UHF satellite positioning",
    }
    """reference identifier table"""

    STRATUM_TABLE = {
        0: "unspecified",
        1: "primary reference",
    }
    """stratum table"""

    MODE_TABLE = {
        0: "unspecified",
        1: "symmetric active",
        2: "symmetric passive",
        3: "client",
        4: "server",
        5: "broadcast",
        6: "reserved for NTP control messages",
        7: "reserved for private use",
    }
    """mode table"""

    LEAP_TABLE = {
        0: "no warning",
        1: "last minute has 61 seconds",
        2: "last minute has 59 seconds",
        3: "alarm condition (clock not synchronized)",
    }
    """leap indicator table"""

class NTPPacket:
    """NTP packet class.

    This represents an NTP packet.
    """

    _PACKET_FORMAT = "!B B B b 11I"
    """packet format to pack/unpack"""

    def __init__(self, source_addr, source_port, version=2, mode=3, tx_timestamp=0):
        """Constructor.

        Parameters:
        version      -- NTP version
        mode         -- packet mode (client, server)
        tx_timestamp -- packet transmit timestamp
        """
        
        self.source_addr = source_addr
        self.source_port = source_port
        
        self.leap = 0
        """leap second indicator"""
        self.version = version
        """version"""
        self.mode = mode
        """mode"""
        self.stratum = 0
        """stratum"""
        self.poll = 0
        """poll interval"""
        self.precision = 0
        """precision"""
        self.root_delay = 0
        """root delay"""
        self.root_dispersion = 0
        """root dispersion"""
        self.ref_id = 0
        """reference clock identifier"""
        self.ref_timestamp = 0
        """reference timestamp"""
        self.orig_timestamp = 0
        self.orig_timestamp_high = 0
        self.orig_timestamp_low = 0
        """originate timestamp"""
        self.recv_timestamp = 0
        """receive timestamp"""
        self.tx_timestamp = tx_timestamp
        self.tx_timestamp_high = 0
        self.tx_timestamp_low = 0
        """tansmit timestamp"""

    def to_data(self):
        """Convert this NTPPacket to a buffer that can be sent over a socket.

        Returns:
        buffer representing this packet

        Raises:
        NTPException -- in case of invalid field
        """
        try:
            packed = struct.pack(NTPPacket._PACKET_FORMAT,
                (self.leap << 6 | self.version << 3 | self.mode),
                self.stratum,
                self.poll,
                self.precision,
                _to_int(self.root_delay) << 16 | _to_frac(self.root_delay, 16),
                _to_int(self.root_dispersion) << 16 |
                _to_frac(self.root_dispersion, 16),
                self.ref_id,
                _to_int(self.ref_timestamp),
                _to_frac(self.ref_timestamp),
                #Change by lichen, avoid loss of precision
                self.orig_timestamp_high,
                self.orig_timestamp_low,
                _to_int(self.recv_timestamp),
                _to_frac(self.recv_timestamp),
                _to_int(self.tx_timestamp),
                _to_frac(self.tx_timestamp))
        except struct.error:
            raise NTPException("Invalid NTP packet fields.")
        return packed

    def from_data(self, data):
        """Populate this instance from a NTP packet payload received from
        the network.

        Parameters:
        data -- buffer payload

        Raises:
        NTPException -- in case of invalid packet format
        """
        print "packet: %s" % (base64.b64encode(data))
        if data == '\x16\x02\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00':
            log(self.source_addr, self.source_port, "Version scan")
            raise NTPException("Version scan")
            return
        try:
            unpacked = struct.unpack(NTPPacket._PACKET_FORMAT,
                    data[0:struct.calcsize(NTPPacket._PACKET_FORMAT)])
        except struct.error:
            raise NTPException("Invalid NTP packet. %s" % base64.b64encode(data))

        self.leap = unpacked[0] >> 6 & 0x3
        self.version = unpacked[0] >> 3 & 0x7
        self.mode = unpacked[0] & 0x7
        self.stratum = unpacked[1]
        self.poll = unpacked[2]
        self.precision = unpacked[3]
        self.root_delay = float(unpacked[4])/2**16
        self.root_dispersion = float(unpacked[5])/2**16
        self.ref_id = unpacked[6]
        self.ref_timestamp = _to_time(unpacked[7], unpacked[8])
        self.orig_timestamp = _to_time(unpacked[9], unpacked[10])
        self.orig_timestamp_high = unpacked[9]
        self.orig_timestamp_low = unpacked[10]
        self.recv_timestamp = _to_time(unpacked[11], unpacked[12])
        self.tx_timestamp = _to_time(unpacked[13], unpacked[14])
        self.tx_timestamp_high = unpacked[13]
        self.tx_timestamp_low = unpacked[14]

    def GetTxTimeStamp(self):
        return (self.tx_timestamp_high,self.tx_timestamp_low)

    def SetOriginTimeStamp(self,high,low):
        self.orig_timestamp_high = high
        self.orig_timestamp_low = low


class RecvThread(threading.Thread):
    def __init__(self,socket):
        threading.Thread.__init__(self)
        self.socket = socket
    def run(self):
        global taskQueue,stopFlag
        while True:
            if stopFlag == True:
                print "RecvThread Ended"
                break
            rlist,wlist,elist = select.select([self.socket],[],[],1);
            if len(rlist) != 0:
                print "Received %d packets" % len(rlist)
                for tempSocket in rlist:
                    try:
                        data,addr = tempSocket.recvfrom(1024)
                        recvTimestamp = recvTimestamp = system_to_ntp_time(time.time())
                        taskQueue.put((data,addr,recvTimestamp))
                    except socket.error,msg:
                        print msg;

class WorkThread(threading.Thread):
    def __init__(self,socket):
        threading.Thread.__init__(self)
        self.socket = socket
    def run(self):
        global taskQueue,stopFlag
        while True:
            if stopFlag == True:
                print "WorkThread Ended"
                break
            try:
                data,addr,recvTimestamp = taskQueue.get(timeout=1)
                recvPacket = NTPPacket(addr[0], addr[1])
                print "Connected from " , addr
                log(addr[0], addr[1])
                try:
                    recvPacket.from_data(data)
                except Exception, e:
                    print e
                    continue
                timeStamp_high,timeStamp_low = recvPacket.GetTxTimeStamp()
                sendPacket = NTPPacket(addr[0], addr[1], version=3,mode=4)
                sendPacket.stratum = 2
                sendPacket.poll = 10
                '''
                sendPacket.precision = 0xfa
                sendPacket.root_delay = 0x0bfa
                sendPacket.root_dispersion = 0x0aa7
                sendPacket.ref_id = 0x808a8c2c
                '''
                sendPacket.ref_timestamp = recvTimestamp-5
                sendPacket.SetOriginTimeStamp(timeStamp_high,timeStamp_low)
                sendPacket.recv_timestamp = recvTimestamp
                sendPacket.tx_timestamp = system_to_ntp_time(0)
                socket.sendto(sendPacket.to_data(),addr)
#                log(addr[0], addr[1])
                #                print "Sent to %s:%d" % (addr[0],addr[1])
                time.sleep(2) # slow.. take it slow ;)
            except Queue.Empty:
                continue



socket = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
socket.bind((listenIp,listenPort))
print "local socket: ", socket.getsockname();
recvThread = RecvThread(socket)
recvThread.start()
workThread = WorkThread(socket)
workThread.start()

while True:
    try:
        time.sleep(2) # slow down
    except KeyboardInterrupt:
        print "Exiting..."
        stopFlag = True
        recvThread.join()
        workThread.join()
        #socket.close()
        print "Exited"
        break


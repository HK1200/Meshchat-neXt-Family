"""Bounded FIFO pacing for BLE RNode firmware without reliable READY events."""
from collections import deque
import threading,time

def packet_delay(size,bitrate):
    # Conservative modem-airtime budget plus a short BLE/CSMA guard. Firmware
    # reports the actual bitrate; this also scales for slower LoRa profiles.
    return max(.25,(size+64)*8/max(float(bitrate or 1200),100)*1.35+.15)

class PacketPacer:
    def __init__(self,write,delay,online,capacity=16):
        self.write=write;self.delay=delay;self.online=online;self.capacity=capacity;self.queue=deque();self.condition=threading.Condition();self.stopped=False;self.last_error='';self.sent=0
        self.worker=threading.Thread(target=self._run,daemon=True);self.worker.start()
    def put(self,data):
        data=bytes(data)
        with self.condition:
            if self.stopped or not self.online():raise OSError('Radio is disconnected')
            if len(self.queue)>=self.capacity:raise OSError('Radio transmit queue is full')
            self.queue.append(data);self.condition.notify_all()
    def _run(self):
        next_send=0
        while True:
            with self.condition:
                while not self.stopped and (not self.queue or time.monotonic()<next_send):self.condition.wait(None if not self.queue else max(0,next_send-time.monotonic()))
                if self.stopped:return
                data=self.queue.popleft()
            if not self.online():continue
            try:self.write(data);self.sent+=1;self.last_error=''
            except Exception as exc:self.last_error=str(exc)[:160]
            next_send=time.monotonic()+self.delay(len(data))
    def pending(self):
        with self.condition:return len(self.queue)
    def stop(self):
        with self.condition:self.stopped=True;self.queue.clear();self.condition.notify_all()

def install(interface):
    original=interface.process_outgoing
    pacer=PacketPacer(original,lambda size:packet_delay(size,interface.bitrate),lambda:interface.online and not interface.detached)
    interface.process_outgoing=pacer.put;interface._family_pacer=pacer
    detach=interface.detach
    def stop():pacer.stop();return detach()
    interface.detach=stop
    return pacer

import time
import serial
import serial.threaded
import threading
import logging
import time

import clr
clr.AddReference('MTBApi, Version=2.12.0.7, Culture=neutral, PublicKeyToken=39820acb30580488')
clr.AddReference('Interop.CZCANSRVLib, Version=7.29.0.0, Culture=neutral, PublicKeyToken=39820acb30580488')

import ZEISS.MTB.Api as MTBAPI
import CZCANSRVLib
import array
from System import Array, Char


logger = logging.getLogger(__name__)


def bytearray_to_str(barray):
    return ' '.join(map(hex, barray))


class CANCommunication:
    """
    Communicate with a CAN device.

    This code uses the MTB framework for writing to the CAN bus, it hence also creates Simulated devices.

    This is opposed to talking to CZCANSRVLib directly, since we then would need to set up the simulated hardware
    ourselves.

    Unfortunately, there is no easy way to access the port from Python directly, precluding MTB style events on
    received messages. We hence use the monitoring capabilities of CZCANSRVLib to subscribe to all received CAN
    bus messages.
    """
    def __init__(self, msg_cb_fun):
        self._conn = MTBAPI.MTBConnection()
        self._login_id = self._conn.Login('en', '')
        self._root = self._conn.GetRoot(self._login_id)
        self._d = self._root.GetDeviceFullConfig(0)

        # Get all the devices of this device
        # This is required for the workaround where the CAN29 enumeration command does not work for simulated
        # hardware.
        devices = [(can_id, self._d.FindComponentByCanID(can_id)) for can_id in range(255)]
        logger.info("Found the following devices via MTB")
        for can_id, device_type in devices:
            if not device_type:
                continue
            logger.info(f'{can_id: 4d}\t{device_type}')

        self._device_ids = tuple([can_id for can_id, device in devices if device])

        # Register a monitor to get the replies on the CAN level
        # FIXME: This registers to all ports and does not differentiate between them.
        self._monitor = CZCANSRVLib.MonitorClass()
        self._monitor.MonitorMode = CZCANSRVLib.CZCom_MonitorMode.CZCom_MonitorMode_AllRawData_ASCII
        self._monitor.MonitorASCII += self.m_Monitor_MonitorASCII
        self._msg_cb_fun = msg_cb_fun

    @property
    def device_ids(self):
        return self._device_ids

    def __del__(self):
        self._monitor.MonitorASCII -= self.m_Monitor_MonitorASCII

    def m_Monitor_MonitorASCII(self, mon_mode, port_nr, err_state, text:str):
        # FIXME: Check for correct port_nr
        if not err_state and '<-' in text:
            msg = bytearray(map(lambda _: int(_, 16), text.split('<-')[-1].split()))
            if self._msg_cb_fun:
                self._msg_cb_fun(msg)

    def send_message(self, destination_addr, source_addr, cmd_class, cmd_number, sub_nr, proc_id, extra_data=None):
        if extra_data:
            x = array.array('B', extra_data)
            extra_data = Array[Char](x)
        else:
            extra_data = ''

        self._d.SendMessage(CZCANSRVLib.CZCom_MessageType.CZCom_MessageType_CAN29,
                            destination_addr, source_addr, cmd_class, cmd_number, sub_nr, proc_id, extra_data)

    def send_raw(self, bytes: bytearray):
        assert bytes[2] == len(bytes) - 5, "Length field of the sent raw string is wrong."
        self.send_message(
            destination_addr=bytes[0],
            source_addr=bytes[1],
            cmd_class=bytes[3],
            cmd_number=bytes[4],
            proc_id=bytes[5],
            sub_nr=bytes[6],
            extra_data=bytes[7:] if len(bytes) > 6 else None
        )

    def send_str(self, string: str):
        self.send_raw(bytearray(map(lambda _: int(_, 16), string.split())))


def encode_can29_message(raw_message: bytearray):
    escaped_msg = bytearray([0x10, 0x02])
    for c in raw_message:
        if c in [0x10, 0x0d]:
            escaped_msg.append(0x10)
        escaped_msg.append(c)
    escaped_msg.extend([0x10, 0x03])
    return escaped_msg


class Can29SerialReceiverProtocol(serial.threaded.Protocol):
    """
    Receive native Zeiss CAN29 messages on a COM port.
    """

    def __init__(self):
        super().__init__()
        self._input_buffer = bytearray()
        self._lock = threading.Lock()

    def data_received(self, data):
        with self._lock:
            self._input_buffer.extend(data)

    def __iter__(self):
        return self

    def __next__(self):
        while True:
            ten_found = False
            message_data = None

            with self._lock:
                for i, c in enumerate(self._input_buffer):
                    if ten_found:
                        ten_found = False

                        if c == 0x02:
                            message_data = bytearray()
                            continue

                        if c == 0x03:
                            self._input_buffer = self._input_buffer[i+1:]

                            if message_data is not None:
                                return message_data

                        if c in [0x0d, 0x10]:
                            if message_data is not None:
                                message_data.append(c)
                            continue

                        raise RuntimeError(f"Got an unexpected character {hex(c)} following a 0x10 character.")

                    if c == 0x10:
                        ten_found = True
                        continue

                    if message_data is not None:
                        message_data.append(c)

            if message_data is None:
                raise StopIteration("No mode current messages in buffer")


def start_can_forwarder(serial_port: str):
    ser = serial.Serial(serial_port, baudrate=57600, timeout=1)
    rt = serial.threaded.ReaderThread(ser, Can29SerialReceiverProtocol)
    with rt as can_input_protocol:
        def msg_cb_fun(raw_message: bytearray):
            print(f'< {bytearray_to_str(raw_message)}')
            rt.write(bytes(raw_message))
            with can_input_protocol._lock:
                can_input_protocol.serial.flushOutput()


        zeiss_can_port = CANCommunication(msg_cb_fun)

        while True:
            # Read in all current messages in the COM port input buffer
            for raw_message in can_input_protocol:
                print(f'> {bytearray_to_str(raw_message)}')

                # Unfortunately, the simulation does not include a full enumeration of the
                # CAN devices attached to a target.
                #
                # We hence fake a reply, claiming that all devices provided by MTB exist.
                if zeiss_can_port._d.Simulated and raw_message[3] == 0x15 and raw_message[4] == 0xa0 and raw_message[6] == 0xfe:
                    print('Fake reply!')
                    logger.debug("Faking an enumeration ")

                    dev_ids = zeiss_can_port.device_ids
                    for i, dev_id in enumerate(dev_ids):
                        reply = bytearray([
                            raw_message[1],  # Reply to code
                            raw_message[0],  # Device id which responds
                            0x04,            # Message length
                            0x09 if (i + 1 == len(dev_ids)) else 0x05,  # Multi-response anwser
                            raw_message[4],  # Find devices
                            raw_message[5],  # ProcID
                            raw_message[6],  # Subid
                            dev_id,
                            3                # FIXME: Unknown what to send here.
                        ])

                        print('<f', bytearray_to_str(reply))
                        rt.write(encode_can29_message(reply))

                    # Do not forward the message to the real Can device
                    continue

                zeiss_can_port.send_raw(raw_message)

            time.sleep(0.01)


def main():
    logging.basicConfig(level=logging.INFO)
    start_can_forwarder(serial_port='COM3')


if __name__ == '__main__':
    main()
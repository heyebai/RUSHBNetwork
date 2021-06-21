import sys
import threading
import socket
import ipaddress

LOCALHOST = "127.0.0.1"
RECV_SIZE = 1500
ORIGINAL_IP = int('00000000',2)
DISCOVERY = int('00000001',2)
OFFER = int('00000010',2)
REQUEST = int('00000011',2)
ACKNOWLEDGE = int('00000100',2)
MODE5 = int('00000101',2)  #data transmission
MODE6 = int('00000110',2)  #ask available for data transmission
MODE7 = int('00000111',2)  #respond for available for receiving data
MODE8 = int('00001000',2)  #location exchange
MODE9 = int('00001001',2)  #broadcast
MODE10 = int('00001010',2) #fragmentation
MODE11 = int('00001011',2) #the end of fragmentation


class Adapter():
    def __init__(self, switch_port):
        self._socket = None
        self._switch_info = (LOCALHOST, switch_port)
        self._my_info = (LOCALHOST, 0)
        self._switch_ip = 0
        self._greeting_flag = True
        
        # self._source_ip_address = 0
        # self._destination_ip_address = 0
        # self._reserved = 0
        # self._mode = 0
        self._ip_address = 0
        
    def connect(self):
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.bind(self._my_info)
            # print(self._socket.getsockname()[1], flush=True)
            return True
        except socket.error as err:
            print("Error encountered when opening socket:\n", err)
            return False

        
    def send_udp_pkt(self, destination_ip, reserved, mode, source_ip=None, info=None, msg=None):
        if info == None:
            info = self._switch_info
        if source_ip == None:
            source_ip = self._ip_address
            
        payload = b''
        if mode == DISCOVERY:
            payload = ORIGINAL_IP.to_bytes(4, byteorder='big')
        elif mode == REQUEST:
            payload = msg.to_bytes(4, byteorder='big')
        elif mode == MODE5:
            payload = msg.encode()
            
        header = self.header_encode(source_ip, destination_ip, reserved, mode)
        # print("send to",info)
        self._socket.sendto(header + payload, info)
        
    def header_decode(self, raw_data, greeting):
        header_info = {}
        header_info["source_ip_address"] = int.from_bytes(raw_data[:4], byteorder='big')
        header_info["destination_ip_address"] = int.from_bytes(raw_data[4:8], byteorder='big')
        header_info["reserved"] = int.from_bytes(raw_data[8:11], byteorder='big')
        header_info["mode"] = int.from_bytes(raw_data[11:12], byteorder='big')
        if greeting:
            header_info["assigned_ip_address"] = int.from_bytes(raw_data[12:16], byteorder='big')
            # print("assigned_ip_address ",socket.inet_ntoa(raw_data[12:16]))
            
        # print("decode")    
        # print("source ",socket.inet_ntoa(raw_data[:4]))
        # print("destination ",socket.inet_ntoa(raw_data[4:8]))
        # print("reserved ", header_info["reserved"])
        # print("mode ", header_info["mode"])
        # print()
        
        return header_info
    
    def header_encode(self, source_ip, destination_ip, reserved, mode):
        source_ip_b = source_ip.to_bytes(4, byteorder='big')
        destination_ip_b = destination_ip.to_bytes(4, byteorder='big')
        reserved_b = reserved.to_bytes(3, byteorder='big')
        mode_b = mode.to_bytes(1, byteorder='big')
        
        # print("encede")
        # print("source ",socket.inet_ntoa(source_ip_b))
        # print("destination ",socket.inet_ntoa(destination_ip_b))
        # print("reserved ", reserved)
        # print("mode ", mode)
        # print()
        
        return source_ip_b + destination_ip_b + reserved_b + mode_b
    
    def run(self):
        while True:
            raw_data, info = self._socket.recvfrom(RECV_SIZE)
            header_info = self.header_decode(raw_data, self._greeting_flag)
            # print("receive", header_info["mode"])
            if header_info["mode"] == OFFER:
                if header_info["destination_ip_address"] == ORIGINAL_IP and header_info["reserved"] == 0:
                    self._switch_ip = header_info["source_ip_address"]
                    # self._ip_address = header_info["assigned_ip_address"]
                    self.send_udp_pkt(self._switch_ip, header_info["reserved"], REQUEST, 
                                      ORIGINAL_IP, self._switch_info, header_info["assigned_ip_address"])
            elif header_info["mode"] == ACKNOWLEDGE:
                if header_info["source_ip_address"] == self._switch_ip and \
                    header_info["destination_ip_address"] == header_info["assigned_ip_address"] and \
                    header_info["reserved"] == 0:
                    self._ip_address = header_info["assigned_ip_address"]
                    self._greeting_flag = False
                    
                    global startUserInput 
                    startUserInput = True
                    # print("self ip", socket.inet_ntoa(self._ip_address.to_bytes(4, byteorder='big')))
            elif header_info["mode"] == MODE5:
                consoleLog(header_info["mode"], raw_data, header_info["source_ip_address"])
            elif header_info["mode"] == MODE6:
                self.send_udp_pkt(self._switch_ip, header_info["reserved"], MODE7)
            elif header_info["mode"] == MODE10 or header_info["mode"] == MODE11:
                consoleLog(header_info["mode"], raw_data, header_info["source_ip_address"])


data = ""
def consoleLog(mode, raw_data, source_ip):
    msg = raw_data[12:].decode()
    source_ip = socket.inet_ntoa(source_ip.to_bytes(4, byteorder='big'))
    global data
    if mode == MODE5:
        print("\b\bReceived from " + source_ip + ": " + msg,flush=True)
        print("> ", end="",flush=True)
    elif mode == MODE10:
        data += msg
    elif mode == MODE11:
        data += msg
        print("\b\bReceived from " + source_ip + ": " + data, flush=True)
        data = ""
        print("> ", end="",flush=True)
            
class UserInput():
    def __init__(self, adapter):
        self._adapter = adapter
        
    def run(self):
        while True:
            try:
                command = input("> ")
            except EOFError as e:
                break
            # print("command",command)
            action, target_ip, message = command.split(" ")
            if message[0] == '"' or message[0] == "'":
                message = message[1:-1]
            if action.strip() == "send":
                target_ip = int(ipaddress.IPv4Address(target_ip.strip()))
                message = message.strip()
                self._adapter.send_udp_pkt(target_ip, 0, MODE5, msg=message)
                
class MyThread (threading.Thread):
    def __init__(self, func):
        threading.Thread.__init__(self)
        self._func = func
        
    def run(self):
        self._func()
       
startUserInput = False
def main(argv):
    adapter = Adapter(int(argv[1]))
    adapter.connect()
    adapter.send_udp_pkt(ORIGINAL_IP, 0, DISCOVERY, ORIGINAL_IP)
    
    userInput = UserInput(adapter)
    # print("argv",argv)
    adapterThread = MyThread(adapter.run)
    
    adapterThread.start()
    global startUserInput
    while True:
        if startUserInput:
            break
    userInputThread = MyThread(userInput.run)
    userInputThread.start()
    userInputThread.join()
    adapterThread.join()
    
    # print("adapter exit")
    
    
if __name__ == "__main__":
    main(sys.argv)
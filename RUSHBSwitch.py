import sys
import ipaddress
import struct
# from socket import *
import threading
import socket
from threading import Timer
import math
import time

LOCALHOST = "127.0.0.1"
RECV_SIZE = 1500
PAYLOAD_SIZE = 1488
MAX_SIZE = 55296
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


def get_next_ip_index(net):
    ip_interface = ipaddress.ip_interface(net)
    net = ipaddress.ip_network(net, False)
    index = 0
    for ip in list(net):
        if int(ip) > int(ip_interface.ip):
            break
        index += 1
    return index

class LocalSwitchU():
    def __init__(self, net, latitude, longitude):
        self._udp_socket = None
        
        self._adapters_info = {}    #int(ip):[socket info (localhost, port), state]
        # self._available_communication = {}  #5s int(ip):socket info (localhost, port)
        
        self._net = ipaddress.ip_network(net, False)
        self._ip_address = int(ipaddress.ip_interface(net))
        self._next_available_ip_index = 1      #get_next_ip_index(net)
        self._next_available_ip = 0
        self._coordinate = (latitude, longitude)
        
        self._tcp_client_info = {} #{server_ip:[assigned_ip, socket, state]} connected switches
        self._switches_distance = {}  #{target_ip:[source_ip(to next switch ip),distance, self_ip]}
        

    def udpConnect(self):
        try:
            self._udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._udp_socket.bind(('', 0))
            print(self._udp_socket.getsockname()[1], flush=True)
            # print(socket.inet_ntoa(self._ip_address.to_bytes(4, byteorder='big')))
            return True
        except socket.error as err:
            print("Error encountered when opening socket:\n", err)
            return False
    
    def recv_udp_pkt(self):
        raw_data, info = self._udp_socket.recvfrom(MAX_SIZE)
        header_info = header_decode(raw_data)
        
        if header_info["mode"] == DISCOVERY:
            if header_info["source_ip_address"] == ORIGINAL_IP and \
                header_info["destination_ip_address"] == ORIGINAL_IP and \
                header_info["reserved"] == 0 and header_info["assigned_ip_address"] == ORIGINAL_IP:
                self.send_udp_pkt(self._ip_address, ORIGINAL_IP, 0, OFFER, info)
        
        elif header_info["mode"] == REQUEST:
            if header_info["source_ip_address"] == ORIGINAL_IP and \
                header_info["destination_ip_address"] == self._ip_address and \
                header_info["reserved"] == 0 and header_info["assigned_ip_address"] == self._next_available_ip:
                self.send_udp_pkt(self._ip_address, self._next_available_ip, 0, ACKNOWLEDGE, info)
        
        elif header_info["mode"] == MODE5 or \
            header_info["mode"] == MODE10 or header_info["mode"] == MODE11:
            if header_info["destination_ip_address"] == self._ip_address:
                consoleLog(header_info["mode"], raw_data, header_info["source_ip_address"])
            else:
                need_to_transmit = True
                for ip in self._tcp_client_info.keys():
                    if self._tcp_client_info[ip][0] == header_info["destination_ip_address"]:
                        consoleLog(header_info["mode"], raw_data, header_info["source_ip_address"])
                        need_to_transmit = False
                        break
                if need_to_transmit:    
                    # tcp min path fregmentation
                    target_ip = find_longest_prefix_ip(self._switches_distance, header_info["destination_ip_address"])
                    next_ip = self._switches_distance[target_ip][0]
                    connect_socket = self._tcp_client_info[next_ip][1]
                    if self._tcp_client_info[next_ip][2] == False:
                        send_tcp_pkt(connect_socket, self._tcp_client_info[next_ip][0],
                                    next_ip, 0, MODE6)
                        # print("mode6 sent")
                        self._tcp_client_info[next_ip][2] = True
                        timer = Timer(5, cancel_connection, (self._tcp_client_info[next_ip], 2,))
                        timer.start()
                    content = raw_data[12:]
                    if len(raw_data) > RECV_SIZE:
                        size = math.ceil(len(content)/PAYLOAD_SIZE)
                        # fragment_list = []
                        reserved = 0
                        for i in range(size):
                            # fragment_list.append(content[i*PAYLOAD_SIZE:(i+1)*PAYLOAD_SIZE])
                            mode = MODE10
                            if i == size - 1:
                                mode = MODE11
                            send_tcp_pkt(connect_socket, header_info["source_ip_address"],
                                        header_info["destination_ip_address"], reserved, mode,
                                        content[i*PAYLOAD_SIZE:(i+1)*PAYLOAD_SIZE])
                            reserved += len(content[i*PAYLOAD_SIZE:(i+1)*PAYLOAD_SIZE])
                    else:
                        # print("else transmitted")
                        time.sleep(0.1)
                        # print(connect_socket)
                        send_tcp_pkt(connect_socket, header_info["source_ip_address"],
                                    header_info["destination_ip_address"], 0, MODE5, content)        
                

        
    def send_udp_pkt(self, source_ip, destination_ip, reserved, mode, info, msg=None):
        payload = b''
        if mode == OFFER:
            self.get_next_ip()
            payload = self._next_available_ip.to_bytes(4, byteorder='big')
        elif mode == ACKNOWLEDGE:
            payload = self._next_available_ip.to_bytes(4, byteorder='big')
            self._adapters_info[destination_ip] = []
            self._adapters_info[destination_ip].append(info)
            self._adapters_info[destination_ip].append(False)
        # elif mode == MODE5:
        #     if 
        header = header_encode(source_ip, destination_ip, reserved, mode)
        self._udp_socket.sendto(header + payload, info)
        
    def get_next_ip(self):
        self._next_available_ip = self._ip_address + self._next_available_ip_index
        self._next_available_ip_index += 1
        
    def runUdp(self):
        while True:
            self.recv_udp_pkt()
            
    # tcp logic client

def broadcast(connected_switches, switches_distance, target_ip, 
              distance, source_ip, connect_socket, self_ip):
    for ip in connected_switches.keys():
        if ip != source_ip:
            # send mode 9
            # print("distance ip", socket.inet_ntoa(ip.to_bytes(4, byteorder='big')))
            # print(switches_distance[ip][1])
            dis = switches_distance[ip][1]
            temp_socket = connected_switches[ip][0]
            if dis + distance <=1000:
                send_tcp_pkt(temp_socket, self_ip, ip, 0, MODE9, (target_ip, dis + distance))
                    
                    
                
            

class GlobalSwitch():
    def __init__(self, net, latitude, longitude):
        self._socket = None
        self._net = ipaddress.ip_network(net, False)
        self._ip_address = int(ipaddress.ip_interface(net))
        self._next_available_ip_index = 1#get_next_ip_index(net)
        self._next_available_ip = 0
        self._coordinate = (latitude, longitude)
        
        self._connected_switches = {}  #{ip:[connect_socket, connect_state]}true false as tcp server
        self._switches_distance = {} #{target_ip:[source_ip(to next switchip),distance, self_ip]}
        
        self._tcp_client_info = {} #{server_ip:[assigned_ip, socket, state]} connected switches
        # self._tcp_client_distance = {}  #{target_ip:[source_ip(to next switchip),distance, self_ip]}
        
    def get_next_ip(self):
        self._next_available_ip = self._ip_address + self._next_available_ip_index
        self._next_available_ip_index += 1
        
    def listen_tcp_port(self):
        self._socket = initialize_tcp_server_socket()
        # print("tcp global",socket.inet_ntoa(self._ip_address.to_bytes(4, byteorder='big')))
        while True:
            connect_socket, client_addr = self._socket.accept()
            # print(client_addr)
            tcpThread = MyThread(self.run, connect_socket)
            tcpThread.start()
            # tcpThread.join()
    
    #tcp server 
    def run(self, connect_socket):
        while True:
            # print("tcp server running")
            raw_data = connect_socket.recv(RECV_SIZE)
            header_info = header_decode(raw_data)
            # print(str(recevent,encoding='gbk'))
            if header_info["mode"] == DISCOVERY:
                if header_info["source_ip_address"] == ORIGINAL_IP and \
                    header_info["destination_ip_address"] == ORIGINAL_IP and \
                    header_info["reserved"] == 0 and header_info["assigned_ip_address"] == ORIGINAL_IP:
                    self.get_next_ip()
                    send_tcp_pkt(connect_socket, self._ip_address, ORIGINAL_IP, 0, OFFER, self._next_available_ip)
            
            elif header_info["mode"] == REQUEST:
                if header_info["source_ip_address"] == ORIGINAL_IP and \
                    header_info["destination_ip_address"] == self._ip_address and \
                    header_info["reserved"] == 0 and header_info["assigned_ip_address"] == self._next_available_ip:
                    send_tcp_pkt(connect_socket, self._ip_address, header_info["assigned_ip_address"], 0, ACKNOWLEDGE, header_info["assigned_ip_address"])
                    self._connected_switches[header_info["assigned_ip_address"]] = [connect_socket, False]

            elif header_info["mode"] == MODE6:
                # print("mode6 received")
                send_tcp_pkt(connect_socket, self._ip_address, header_info["source_ip_address"], 0, MODE7)
                # for ip in self._connected_switches.keys():
                    # print("sourceip", socket.inet_ntoa(ip.to_bytes(4, byteorder='big')))
                self._connected_switches[header_info["source_ip_address"]][1] = True
                # print("mode 7 send")
                timer = Timer(5, cancel_connection, (self._connected_switches[header_info["source_ip_address"]], 1,))
                timer.start()
                # timer
            
            elif header_info["mode"] == MODE8:
                distance = calculate_distance(raw_data, self._coordinate)
                self._switches_distance[header_info["source_ip_address"]] = [header_info["source_ip_address"], distance, self._ip_address]
                
                # for ip in self._switches_distance.keys():
                #     print("distance ip", socket.inet_ntoa(ip.to_bytes(4, byteorder='big')))
                #     print("distance",self._switches_distance[ip][1])
                #     print("distance sourceip", socket.inet_ntoa(self._switches_distance[ip][0].to_bytes(4, byteorder='big')))
                #     print("---------------------------------------")
     
                # broadcast server
                broadcast(self._connected_switches, self._switches_distance, 
                        header_info["source_ip_address"], distance, header_info["source_ip_address"],
                        connect_socket, self._ip_address)
                # broadcast client
                for ip in self._tcp_client_info.keys():
                    dis = self._switches_distance[ip][1]
                    temp_socket = self._tcp_client_info[ip][1]
                    temp_source_ip = self._tcp_client_info[ip][0]
                    if dis + distance <= 1000 and ip != header_info["source_ip_address"]:
                        send_tcp_pkt(temp_socket, temp_source_ip, ip, 0, MODE9, 
                                    (header_info["source_ip_address"], dis + distance))
                send_tcp_pkt(connect_socket, self._ip_address, header_info["source_ip_address"], 0, MODE8, self._coordinate)
            
            elif header_info["mode"] == MODE9:
                target_ip = int.from_bytes(raw_data[12:16], byteorder='big')
                distance = int.from_bytes(raw_data[16:20], byteorder='big')
                # print("mode0 targetip", socket.inet_ntoa(target_ip.to_bytes(4, byteorder='big')))
                
                
                if not self._switches_distance.__contains__(target_ip):
                    self._switches_distance[target_ip] = [header_info["source_ip_address"], distance, self._ip_address]
                    # broadcast
                    broadcast(self._connected_switches, self._switches_distance,
                            target_ip, distance, header_info["source_ip_address"],
                            connect_socket, self._ip_address)
                    # broadcast client
                    for ip in self._tcp_client_info.keys():
                        dis = self._switches_distance[ip][1]
                        temp_socket = self._tcp_client_info[ip][1]
                        temp_source_ip = self._tcp_client_info[ip][0]
                        if dis + distance <= 1000 and ip != header_info["source_ip_address"]:
                            send_tcp_pkt(temp_socket, temp_source_ip, ip, 0, MODE9, 
                                        (target_ip, dis + distance))
                    
                else:
                    if self._switches_distance[target_ip][1] > distance:
                        self._switches_distance[target_ip][0] = header_info["source_ip_address"]
                        self._switches_distance[target_ip][1] = distance
                        # broadcast
                        broadcast(self._connected_switches, self._switches_distance,
                                target_ip, distance, header_info["source_ip_address"],
                                connect_socket, self._ip_address)
                        for ip in self._tcp_client_info.keys():
                            dis = self._switches_distance[ip][1]
                            temp_socket = self._tcp_client_info[ip][1]
                            temp_source_ip = self._tcp_client_info[ip][0]
                            if dis + distance <= 1000 and ip != header_info["source_ip_address"]:
                                send_tcp_pkt(temp_socket, temp_source_ip, ip, 0, MODE9, 
                                            (target_ip, dis + distance))
            
            elif header_info["mode"] == MODE5 or \
                header_info["mode"] == MODE10 or header_info["mode"] == MODE11:
                # print("mode5 received")
                if header_info["destination_ip_address"] == self._ip_address:
                    consoleLog(header_info["mode"], raw_data, header_info["source_ip_address"])
                else:
                    need_to_transmit = True
                    for server_ip in self._tcp_client_info.keys():
                        if header_info["destination_ip_address"] == self._tcp_client_info[server_ip][0]:
                            consoleLog(header_info["mode"], raw_data, header_info["source_ip_address"])
                            need_to_transmit = False
                            break
                    if need_to_transmit:
                        target_ip = find_longest_prefix_ip(self._switches_distance, header_info["destination_ip_address"])
                        next_ip = self._switches_distance[target_ip][0]
                        client = False
                        # if self._switches_distance[next_ip][2] == self._ip_address:
                        #     connect_socket = self._connected_switches[next_ip][0]
                        # else: 
                        #     next_switch_ip = self._switches_distance[next_ip][0]
                        #     connect_socket = self._tcp_client_info[next_switch_ip][1]
                        #     client = True
                        # print("nextip", socket.inet_ntoa(next_ip.to_bytes(4, byteorder='big')))
                        
                        if self._connected_switches.__contains__(next_ip):
                            temp_connect_socket = self._connected_switches[next_ip][0]
                        else:
                            temp_connect_socket = self._tcp_client_info[next_ip][1]
                            client = True
                            
                        if not client:
                            if self._connected_switches[next_ip][1] == False:
                                send_tcp_pkt(temp_connect_socket, self._ip_address,
                                            next_ip, 0, MODE6)
                                self._connected_switches[next_ip][1] = True
                                timer = Timer(5, cancel_connection, (self._connected_switches[next_ip], 1,))
                                timer.start()
                        else:
                            if self._tcp_client_info[next_ip][2] == False:
                                send_tcp_pkt(temp_connect_socket, self._tcp_client_info[next_ip][0],
                                            next_ip, 0, MODE6)
                                self._tcp_client_info[next_ip][2] = True
                                timer = Timer(5, cancel_connection, (self._tcp_client_info[next_ip], 2,))
                                timer.start()
                                
                        # print("mode 6 send")        
                        content = raw_data[12:]
                        send_tcp_pkt(temp_connect_socket, header_info["source_ip_address"],
                                    header_info["destination_ip_address"], 0, header_info["mode"], content)        
            
            elif header_info["mode"] == MODE7:
                pass
                # print("received mode 7 in global tcpserver")  
    
    
def send_tcp_pkt(connect_socket, source_ip, destination_ip, reserved, mode, msg=None):
    header = header_encode(source_ip, destination_ip, reserved, mode)
    payload = b''
    if mode == OFFER or mode == ACKNOWLEDGE or mode == DISCOVERY or mode == REQUEST:
        payload = msg.to_bytes(4, byteorder='big')
    elif mode == MODE8:
        payload += msg[0].to_bytes(2, byteorder='big') #latitude
        payload += msg[1].to_bytes(2, byteorder='big') #longitude
    elif mode == MODE9:
        payload += msg[0].to_bytes(4, byteorder='big') #target ip
        payload += msg[1].to_bytes(4, byteorder='big') #distance
    elif mode == MODE5 or mode == MODE10 or mode == MODE11:
        payload += msg
    connect_socket.send(header + payload)
    
# def transmit_tcp_pkt(connect)


# def tcp_greeting_sender(connect_socket, raw_data):
#     header_info = header_decode(raw_data)
#     if header_info["mode"] == OFFER:
#         if header_info["destination_ip_address"] == ORIGINAL_IP and header_info["reserved"] == 0:

class LocalSwitchUT():
    def __init__(self, localNet, globalNet, latitude, longitude):
        self._local_net = ipaddress.ip_network(localNet, False)
        self._global_net = ipaddress.ip_network(globalNet, False)
        self._local_ip_address = int(ipaddress.ip_interface(localNet))
        self._global_ip_address = int(ipaddress.ip_interface(globalNet))
        self._next_available_local_ip_index = 1 #get_next_ip_index(localNet)
        self._next_available_global_ip_index = 1 #get_next_ip_index(globalNet)
        self._next_available_local_ip = 0
        self._next_available_global_ip = 0
        
        self._coordinate = (latitude, longitude)
        
        self._tcp_socket = None
        self._udp_socket = None
        
        self._adapters_info = {}  #int(ip):[socket info (localhost, port), state]
        
        self._connected_switches = {}  #{ip:[connect_socket, connect_state]}true false as tcp server
        self._switches_distance = {}    #{target_ip:[source_ip(to next switch的ip),distance]}
        
        
    def get_next_local_ip(self):
        self._next_available_local_ip = self._local_ip_address + self._next_available_local_ip_index
        self._next_available_local_ip_index += 1
        
    def get_next_global_ip(self):
        self._next_available_global_ip = self._global_ip_address + self._next_available_global_ip_index
        self._next_available_global_ip_index += 1
        
    def udpConnect(self):
        try:
            self._udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._udp_socket.bind(('', 0))
            print(self._udp_socket.getsockname()[1], flush=True)
            # print("self local ip", socket.inet_ntoa(self._local_ip_address.to_bytes(4, byteorder='big')))
            # print("self global ip", socket.inet_ntoa(self._global_ip_address.to_bytes(4, byteorder='big')))
            
            return True
        except socket.error as err:
            print("Error encountered when opening socket:\n", err)
            return False
        
    def recv_udp_pkt(self):
        raw_data, info = self._udp_socket.recvfrom(MAX_SIZE)
        header_info = header_decode(raw_data)
        
        if header_info["mode"] == DISCOVERY:
            if header_info["source_ip_address"] == ORIGINAL_IP and \
                header_info["destination_ip_address"] == ORIGINAL_IP and \
                header_info["reserved"] == 0 and header_info["assigned_ip_address"] == ORIGINAL_IP:
                self.send_udp_pkt(self._local_ip_address, ORIGINAL_IP, 0, OFFER, info)
        
        elif header_info["mode"] == REQUEST:
            if header_info["source_ip_address"] == ORIGINAL_IP and \
                header_info["destination_ip_address"] == self._local_ip_address and \
                header_info["reserved"] == 0 and header_info["assigned_ip_address"] == self._next_available_local_ip:
                self.send_udp_pkt(self._local_ip_address, self._next_available_local_ip, 0, ACKNOWLEDGE, info)
        
        elif header_info["mode"] == MODE5 or \
            header_info["mode"] == MODE10 or header_info["mode"] == MODE11:
            if header_info["destination_ip_address"] == self._local_ip_address or \
                header_info["destination_ip_address"] == self._global_ip_address:
                consoleLog(header_info["mode"], raw_data, header_info["source_ip_address"])
            else:
                # tcp min path fregmentation
                # need_to_transmit = True
                # for ip in self._tcp_client_info.keys():
                #     if self._tcp_client_info[ip][0] == header_info["destination_ip_address"]:
                #         consoleLog(header_info["mode"], raw_data, header_info["source_ip_address"])
                #         need_to_transmit = False
                #         break
                # if need_to_transmit:    
                target_ip = find_longest_prefix_ip(self._switches_distance, header_info["destination_ip_address"])
                next_ip = self._switches_distance[target_ip][0]
                # print("localut nextip", socket.inet_ntoa(next_ip.to_bytes(4, byteorder='big')))
                
                connect_socket = self._connected_switches[next_ip][0]
                if self._connected_switches[next_ip][1] == False:
                    send_tcp_pkt(connect_socket, self._global_ip_address,
                                next_ip, 0, MODE6)
                    self._connected_switches[next_ip][1] = True
                    timer = Timer(5, cancel_connection, (self._connected_switches[next_ip], 1,))
                    timer.start()
                content = raw_data[12:]
                if len(raw_data) > RECV_SIZE:
                    size = math.ceil(len(content)/PAYLOAD_SIZE)
                    # fragment_list = []
                    reserved = 0
                    for i in range(size):
                        # fragment_list.append(content[i*PAYLOAD_SIZE:(i+1)*PAYLOAD_SIZE])
                        mode = MODE10
                        if i == size - 1:
                            mode = MODE11
                        send_tcp_pkt(connect_socket, header_info["source_ip_address"],
                                    header_info["destination_ip_address"], reserved, mode,
                                    content[i*PAYLOAD_SIZE:(i+1)*PAYLOAD_SIZE])
                        reserved += len(content[i*PAYLOAD_SIZE:(i+1)*PAYLOAD_SIZE])
                else:
                    send_tcp_pkt(connect_socket, header_info["source_ip_address"],
                                header_info["destination_ip_address"], 0, MODE5, content)        
                
            
    def send_udp_pkt(self, source_ip, destination_ip, reserved, mode, info, msg=None):
        payload = b''
        if mode == OFFER:
            self.get_next_local_ip()
            payload = self._next_available_local_ip.to_bytes(4, byteorder='big')
        elif mode == ACKNOWLEDGE:
            payload = self._next_available_local_ip.to_bytes(4, byteorder='big')
            self._adapters_info[destination_ip] = []
            self._adapters_info[destination_ip].append(info)
            self._adapters_info[destination_ip].append(False)
        elif mode == MODE5:
            payload += msg
        header = header_encode(source_ip, destination_ip, reserved, mode)
        self._udp_socket.sendto(header + payload, info)
        
    def runUdp(self):
        while True:
            self.recv_udp_pkt()
    
    def listen_tcp_port(self):
        self._tcp_socket = initialize_tcp_server_socket()
        # print("tcp for localUT",socket.inet_ntoa(self._ip_address.to_bytes(4, byteorder='big')))
        while True:
            connect_socket, client_addr = self._tcp_socket.accept()
            # print(client_addr)
            tcpThread = MyThread(self.run, connect_socket)
            tcpThread.start()
            
    #tcp server 
    def run(self, connect_socket):
        while True:
            raw_data = connect_socket.recv(RECV_SIZE)
            header_info = header_decode(raw_data)
            
            if header_info["mode"] == DISCOVERY:
                if header_info["source_ip_address"] == ORIGINAL_IP and \
                    header_info["destination_ip_address"] == ORIGINAL_IP and \
                    header_info["reserved"] == 0 and header_info["assigned_ip_address"] == ORIGINAL_IP:
                    self.get_next_global_ip()
                    send_tcp_pkt(connect_socket, self._global_ip_address, ORIGINAL_IP, 0, OFFER, self._next_available_global_ip)
            
            elif header_info["mode"] == REQUEST:
                if header_info["source_ip_address"] == ORIGINAL_IP and \
                    header_info["destination_ip_address"] == self._global_ip_address and \
                    header_info["reserved"] == 0 and header_info["assigned_ip_address"] == self._next_available_global_ip:
                    send_tcp_pkt(connect_socket, self._global_ip_address, header_info["assigned_ip_address"], 0, ACKNOWLEDGE, header_info["assigned_ip_address"])
                    self._connected_switches[header_info["assigned_ip_address"]] = [connect_socket, False]

            elif header_info["mode"] == MODE6:
                # print("mode 6 received")
                send_tcp_pkt(connect_socket, self._global_ip_address, header_info["source_ip_address"], 0, MODE7)
                # print("mode 7 send")
                self._connected_switches[header_info["source_ip_address"]][1] = True
                
                timer = Timer(5, cancel_connection, (self._connected_switches[header_info["source_ip_address"]], 1,))
                timer.start()
                # timer   
            
            elif header_info["mode"] == MODE8:
                distance = calculate_distance(raw_data, self._coordinate)
                self._switches_distance[header_info["source_ip_address"]] = [header_info["source_ip_address"], distance, self._global_ip_address]
                broadcast(self._connected_switches, self._switches_distance, 
                        header_info["source_ip_address"], distance, header_info["source_ip_address"],
                        connect_socket, self._global_ip_address)
                
                send_tcp_pkt(connect_socket, self._global_ip_address, 
                             header_info["source_ip_address"], 0, MODE8, 
                             self._coordinate)
                # print("localUT mode8 send")
                time.sleep(0.1)
                send_tcp_pkt(connect_socket, self._global_ip_address, 
                             header_info["source_ip_address"], 0, MODE9, 
                             (self._local_ip_address, distance))
                # print("localUT mode9 send")
            
            elif header_info["mode"] == MODE9:
                target_ip = int.from_bytes(raw_data[12:16], byteorder='big')
                distance = int.from_bytes(raw_data[16:20], byteorder='big')
                if not self._switches_distance.__contains__(target_ip):
                    self._switches_distance[target_ip] = [header_info["source_ip_address"], distance]
                    # broadcast
                    broadcast(self._connected_switches, self._switches_distance,
                            target_ip, distance, header_info["source_ip_address"],
                            connect_socket, self._global_ip_address)
                    # for ip in broadcast_ips:
                    #     timer = Timer(5, cancel_connection, (self._connected_switches[ip], 1,))
                    #     timer.start()
                else:
                    if self._switches_distance[target_ip][1] > distance:
                        self._switches_distance[target_ip][0] = header_info["source_ip_address"]
                        self._switches_distance[target_ip][1] = distance
                        # broadcast
                        broadcast(self._connected_switches, self._switches_distance,
                                target_ip, distance, header_info["source_ip_address"],
                                connect_socket, self._global_ip_address)
                        # for ip in broadcast_ips:
                        #     timer = Timer(5, cancel_connection, (self._connected_switches[ip], 1,))
                        #     timer.start()
                        
            elif header_info["mode"] == MODE5 or \
                header_info["mode"] == MODE10 or header_info["mode"] == MODE11:
                if header_info["destination_ip_address"] == self._global_ip_address or \
                    header_info["destination_ip_address"] == self._local_ip_address:
                    consoleLog(header_info["mode"], raw_data, header_info["source_ip_address"])
                    # for ip in self._connected_switches.keys():
                    #     print("connect ip", socket.inet_ntoa(ip.to_bytes(4, byteorder='big')))
                        # print("distance",self._switches_distance[ip][1])
                        # print("distance sourceip", socket.inet_ntoa(self._switches_distance[ip][0].to_bytes(4, byteorder='big')))
                        # print("---------------------------------------")
                else:
                    # send to adapter
                    if self._adapters_info[header_info["destination_ip_address"]][1] == False:
                        self.send_udp_pkt(self._local_ip_address, header_info["destination_ip_address"],
                                          0, MODE6, self._adapters_info[header_info["destination_ip_address"]][0])
                        self._adapters_info[header_info["destination_ip_address"]][1] == True
                        timer = Timer(5, cancel_connection, (self._adapters_info[header_info["destination_ip_address"]], 1,))
                        timer.start()
                    self.send_udp_pkt(header_info["source_ip_address"], header_info["destination_ip_address"],
                                        header_info["reserved"], header_info["mode"], 
                                        self._adapters_info[header_info["destination_ip_address"]][0],
                                        raw_data[12:])
            
            
                     
def cancel_connection(connection_pool, index):
     connection_pool[index] = False
    #  print("connection cancel")
            

def header_decode(raw_data):
    header_info = {}
    header_info["source_ip_address"] = int.from_bytes(raw_data[:4], byteorder='big')
    header_info["destination_ip_address"] = int.from_bytes(raw_data[4:8], byteorder='big')
    header_info["reserved"] = int.from_bytes(raw_data[8:11], byteorder='big')
    header_info["mode"] = int.from_bytes(raw_data[11:12], byteorder='big')
    if header_info["mode"] <= 4:
        header_info["assigned_ip_address"] = int.from_bytes(raw_data[12:16], byteorder='big')
    #     print("assigned_ip_address ",socket.inet_ntoa(raw_data[12:16]))
        
    # print("decode")    
    # print("source ",socket.inet_ntoa(raw_data[:4]))
    # print("destination ",socket.inet_ntoa(raw_data[4:8]))
    # print("reserved ", header_info["reserved"])
    # print("mode ", header_info["mode"])
    # print()
    
    return header_info

def header_encode(source_ip, destination_ip, reserved, mode):
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
        
def initialize_tcp_server_socket():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM) #socket
    server_socket.bind((LOCALHOST, 0))
    print(server_socket.getsockname()[1], flush=True)
    server_socket.listen(5)
    return server_socket

# tcp client and send discovery
def tcp_connect(port):
    addr = (LOCALHOST, port)
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM) ## socket
    client_socket.connect(addr)
    # send discovery
    send_tcp_pkt(client_socket, ORIGINAL_IP, ORIGINAL_IP, 0, DISCOVERY, ORIGINAL_IP)
    return client_socket

def tcp_client_run(Tcp_client, client_socket, local_flag=False):
    while True:
        raw_data = client_socket.recv(RECV_SIZE)
        header_info = header_decode(raw_data)
        if header_info["mode"] == OFFER:
            if header_info["destination_ip_address"] == ORIGINAL_IP and header_info["reserved"] == 0:
                Tcp_client._tcp_client_info[header_info["source_ip_address"]] = []
                send_tcp_pkt(client_socket, ORIGINAL_IP, header_info["source_ip_address"], 
                             0, REQUEST, header_info["assigned_ip_address"])
                
        elif header_info["mode"] == ACKNOWLEDGE:
            Tcp_client._tcp_client_info[header_info["source_ip_address"]].append(header_info["assigned_ip_address"]) #0:assigned_ip
            Tcp_client._tcp_client_info[header_info["source_ip_address"]].append(client_socket) #1:socket
            Tcp_client._tcp_client_info[header_info["source_ip_address"]].append(False) #2:state
            send_tcp_pkt(client_socket, header_info["assigned_ip_address"], header_info["source_ip_address"],
                         0, MODE8, Tcp_client._coordinate)
            # print("client mode8 send")
            
        elif header_info["mode"] == MODE8:
            distance = calculate_distance(raw_data, Tcp_client._coordinate)
            Tcp_client._switches_distance[header_info["source_ip_address"]] = []
            Tcp_client._switches_distance[header_info["source_ip_address"]].append(header_info["source_ip_address"]) #0:sourceip next switch to target ip
            Tcp_client._switches_distance[header_info["source_ip_address"]].append(distance) #1:distance
            Tcp_client._switches_distance[header_info["source_ip_address"]].append(header_info["destination_ip_address"]) #2:selfip
            # print("mode8 received")
            # for ip in Tcp_client._switches_distance.keys():
            #     print("distance ip", socket.inet_ntoa(ip.to_bytes(4, byteorder='big')))
            #     print("distance",Tcp_client._switches_distance[ip][1])
            #     print("distance sourceip", socket.inet_ntoa(Tcp_client._switches_distance[ip][0].to_bytes(4, byteorder='big')))
            #     print("---------------------------------------")
                    

            if not local_flag:
                broadcast(Tcp_client._connected_switches, Tcp_client._switches_distance,
                        header_info["source_ip_address"], distance, header_info["source_ip_address"],
                        client_socket, Tcp_client._ip_address)
            for ip in Tcp_client._tcp_client_info.keys():
                dis = Tcp_client._switches_distance[ip][1]
                temp_socket = Tcp_client._tcp_client_info[ip][1]
                temp_source_ip = Tcp_client._tcp_client_info[ip][0]
                if dis + distance <= 1000 and ip != header_info["source_ip_address"]:
                    send_tcp_pkt(temp_socket, temp_source_ip, ip, 0, MODE9, 
                                (header_info["source_ip_address"], dis + distance))
            
        elif header_info["mode"] == MODE9:
            target_ip = int.from_bytes(raw_data[12:16], byteorder='big')
            distance = int.from_bytes(raw_data[16:20], byteorder='big')
            # print("mode9 received")
            
            if not Tcp_client._switches_distance.__contains__(target_ip):
                Tcp_client._switches_distance[target_ip] = [header_info["source_ip_address"], distance, header_info["destination_ip_address"]]
                
                # for ip in Tcp_client._switches_distance.keys():
                #     print("distance ip", socket.inet_ntoa(ip.to_bytes(4, byteorder='big')))
                #     print("distance",Tcp_client._switches_distance[ip][1])
                #     print("distance sourceip", socket.inet_ntoa(Tcp_client._switches_distance[ip][0].to_bytes(4, byteorder='big')))
                #     print("---------------------------------------")
     
                if not local_flag:
                    broadcast(Tcp_client._connected_switches, Tcp_client._switches_distance,
                            target_ip, distance, header_info["source_ip_address"],
                            client_socket, Tcp_client._ip_address)
                for ip in Tcp_client._tcp_client_info.keys():
                #     print("client info ip", socket.inet_ntoa(ip.to_bytes(4, byteorder='big')))
                    
                    dis = Tcp_client._switches_distance[ip][1]
                    temp_socket = Tcp_client._tcp_client_info[ip][1]
                    temp_source_ip = Tcp_client._tcp_client_info[ip][0]
                    if dis + distance <= 1000 and ip != header_info["source_ip_address"]:
                        send_tcp_pkt(temp_socket, temp_source_ip, ip, 0, MODE9, 
                                    (target_ip, dis + distance))
            else:
                if Tcp_client._switches_distance[target_ip][1] > distance:
                    Tcp_client._switches_distance[target_ip][0] = header_info["source_ip_address"]
                    Tcp_client._switches_distance[target_ip][1] = distance
                if not local_flag:
                    broadcast(Tcp_client._connected_switches, Tcp_client._switches_distance,
                            target_ip, distance, header_info["source_ip_address"],
                            client_socket, Tcp_client._ip_address)
                for ip in Tcp_client._tcp_client_info.keys():
                    dis = Tcp_client._switches_distance[ip][1]
                    temp_socket = Tcp_client._tcp_client_info[ip][1]
                    temp_source_ip = Tcp_client._tcp_client_info[ip][0]
                    if dis + distance <= 1000 and ip != header_info["source_ip_address"]:
                        send_tcp_pkt(temp_socket, temp_source_ip, ip, 0, MODE9, 
                                    (target_ip, dis + distance)) 
                    # for ip in broadcast_ips:
                    #     timer = Timer(5, cancel_connection, (Tcp_client._connected_switches[ip], 1,))
                    #     timer.start()
            # for ip in Tcp_client._switches_distance.keys():
            #     print("distance ip", socket.inet_ntoa(ip.to_bytes(4, byteorder='big')))
            #     print("distance",Tcp_client._switches_distance[ip][1])
            #     print("distance sourceip", socket.inet_ntoa(Tcp_client._switches_distance[ip][0].to_bytes(4, byteorder='big')))
            #     print("---------------------------------------")
                    
        elif header_info["mode"] == MODE6:
            send_tcp_pkt(client_socket, header_info["destination_ip_address"], 
                         header_info["source_ip_address"], 0, MODE7)
            Tcp_client._tcp_client_info[header_info["source_ip_address"]][2] = True
            timer = Timer(5, cancel_connection, (Tcp_client._tcp_client_info[header_info["source_ip_address"]], 2,))
            timer.start()
            # timer to cancel
            
        elif header_info["mode"] == MODE5 or \
            header_info["mode"] == MODE10 or header_info["mode"] == MODE11:
            if header_info["destination_ip_address"] == Tcp_client._ip_address:
                consoleLog(header_info["mode"], raw_data, header_info["source_ip_address"])
            else:
                need_to_transmit = True
                for server_ip in Tcp_client._tcp_client_info.keys():
                    if header_info["destination_ip_address"] == Tcp_client._tcp_client_info[server_ip][0]:
                        consoleLog(header_info["mode"], raw_data, header_info["source_ip_address"])
                        need_to_transmit = False
                        break
                if need_to_transmit:
                    if local_flag:
                        if Tcp_client._adapters_info[header_info["destination_ip_address"]][1] == False:
                            Tcp_client.send_udp_pkt(Tcp_client._ip_address, header_info["destination_ip_address"],
                                                0, MODE6, Tcp_client._adapters_info[header_info["destination_ip_address"]][0])
                            Tcp_client._adapters_info[header_info["destination_ip_address"]][1] == True
                            timer = Timer(5, cancel_connection, (Tcp_client._adapters_info[header_info["destination_ip_address"]], 1,))
                            timer.start()
                        Tcp_client.send_udp_pkt(header_info["source_ip_address"], header_info["destination_ip_address"],
                                                header_info["reserved"], header_info["mode"], 
                                                Tcp_client._adapters_info[header_info["destination_ip_address"]][0],
                                                raw_data[12:])
                    else:
                        target_ip = find_longest_prefix_ip(Tcp_client._switches_distance, header_info["destination_ip_address"])
                        next_ip = Tcp_client._switches_distance[target_ip][0]
                        client = False
                        # if Tcp_client._switches_distance[next_ip][2] == Tcp_client._ip_address:
                        #     connect_socket = Tcp_client._connected_switches[next_ip][0]
                        # else: 
                        #     # may have some issues
                        #     connect_socket = Tcp_client._tcp_client_info[next_ip][1]
                        #     client = True
                        if local_flag:
                            connect_socket = Tcp_client._tcp_client_info[target_ip][1]
                            client = True
                        else:
                            if Tcp_client._connected_switches.__contains__(next_ip):
                                connect_socket = Tcp_client._connected_switches[next_ip][0]
                            else:
                                connect_socket = Tcp_client._tcp_client_info[next_ip][1]
                                client = True 
                            
                        if not client:
                            if Tcp_client._connected_switches[next_ip][1] == False:
                                send_tcp_pkt(connect_socket, Tcp_client._ip_address,
                                            next_ip, 0, MODE6)
                                Tcp_client._connected_switches[next_ip][1] = True
                                timer = Timer(5, cancel_connection, (Tcp_client._connected_switches[next_ip], 1,))
                                timer.start()
                        else:
                            if Tcp_client._tcp_client_info[next_ip][2] == False:
                                send_tcp_pkt(connect_socket, Tcp_client._tcp_client_info[next_ip][0],
                                            next_ip, 0, MODE6)
                                Tcp_client._tcp_client_info[next_ip][2] = True
                                timer = Timer(5, cancel_connection, (Tcp_client._tcp_client_info[next_ip], 2,))
                                timer.start()
                        content = raw_data[12:]
                        # if len(raw_data) > RECV_SIZE:
                        #     size = math.ceil(len(content)/PAYLOAD_SIZE)
                        #     # fragment_list = []
                        #     reserved = 0
                        #     for i in range(size):
                        #         # fragment_list.append(content[i*PAYLOAD_SIZE:(i+1)*PAYLOAD_SIZE])
                        #         mode = MODE10
                        #         if i == size - 1:
                        #             mode = MODE11
                        #         send_tcp_pkt(connect_socket, header_info["source_ip_address"],
                        #                     header_info["destination_ip_address"], reserved, mode,
                        #                     content[i*PAYLOAD_SIZE:(i+1)*PAYLOAD_SIZE])
                        #         reserved += len(content[i*PAYLOAD_SIZE:(i+1)*PAYLOAD_SIZE])
                        # else:
                        send_tcp_pkt(connect_socket, header_info["source_ip_address"],
                                    header_info["destination_ip_address"], 0, header_info["mode"], content)        
                                
        elif header_info["mode"] == MODE7:
            pass
            # print("received mode 7 in tcpclient")

def calculate_distance(raw_data, coordinate):
    latitude = int.from_bytes(raw_data[12:14], byteorder='big')
    longitude = int.from_bytes(raw_data[14:16], byteorder='big')
    temp = pow(latitude - coordinate[0], 2) + pow(longitude - coordinate[1], 2)
    return math.floor(pow(temp, 0.5))

def find_longest_prefix_ip(switches_distance, destination_ip):
    longest_prefix_ip = 0
    longest_prefix_count = 0
    for ip in switches_distance.keys():
        prefix_count = 0
        bin_ip = bin(ip)
        for index, data in enumerate(bin(destination_ip)):
            if bin_ip[index] == data:
                prefix_count += 1
            else:
                break
        if prefix_count > longest_prefix_count:
            longest_prefix_count = prefix_count
            longest_prefix_ip = ip
    # print("targetip", socket.inet_ntoa(longest_prefix_ip.to_bytes(4, byteorder='big')))
    
    return longest_prefix_ip
    
    
       
data = ""
def consoleLog(mode, raw_data, source_ip):
    msg = raw_data[12:].decode()
    source_ip = socket.inet_ntoa(source_ip.to_bytes(4, byteorder='big'))
    global data
    if mode == MODE5:
        print("\b\bReceived from " + source_ip + ": " + msg, flush=True)
        print("> ", end="", flush=True)
    elif mode == MODE10:
        data += msg
    elif mode == MODE11:
        data += msg
        print("\b\bReceived from " + source_ip + ": " + data, flush=True)
        data = ""
        print("> ", end="", flush=True)
        
class UserInput():
    def __init__(self, switch, local_flag):
        self._switch = switch
        self._local_flag = local_flag
        
    def run(self):
        while True:
            try:
                command = input("> ")
            except EOFError as e:
                break
            # print("command",command)
            action, port = command.split(" ")
            
            if action.strip() == "connect":
                target_ip = int(port.strip())
                client_socket = tcp_connect(target_ip)
                tcp_client = MyThread(tcp_client_run, self._switch, client_socket, self._local_flag)
                tcp_client.start()
                # tcp_client.join()
                
class MyThread (threading.Thread):
    def __init__(self, func, *args):
        threading.Thread.__init__(self)
        self._func = func
        self._args = args
        
    def run(self):
        if len(self._args) == 3:
            Tcp_client, client_socket, local_flag = self._args
            self._func(Tcp_client, client_socket, local_flag)
        elif len(self._args) == 1:
            connect_socket = self._args[0]
            self._func(connect_socket)
        else:
            self._func()

def main(argv):
    # print(argv)
    local_flag = False
    localUT_flag = False
    if argv[1] == "local":
        if len(argv) == 5:
            switch = LocalSwitchU(argv[2], int(argv[3]), int(argv[4]))
            switch.udpConnect()
            local_flag = True
            switchThread = MyThread(switch.runUdp)
            switchThread.start()
        elif len(argv) == 6:
            switch = LocalSwitchUT(argv[2], argv[3], int(argv[4]), int(argv[5]))
            switch.udpConnect()
            localUT_flag = True
            switchUdpThread = MyThread(switch.runUdp)
            
            switchTcpThread = MyThread(switch.listen_tcp_port)
            switchUdpThread.start()
            
            switchTcpThread.start()
    elif argv[1] == "global":
        switch = GlobalSwitch(argv[2], int(argv[3]), int(argv[4]))
        switchThread = MyThread(switch.listen_tcp_port)
        switchThread.start()
    
    userInput = UserInput(switch, local_flag)
    # print("argv",argv)
    
    userInputThread = MyThread(userInput.run)
    
    
    userInputThread.start()
    if localUT_flag:
        switchUdpThread.join()
        switchTcpThread.join()
        # pass
    else:
        switchThread.join()
    
    userInputThread.join()
    
    # print("switch exit")
    # while True:
    #     content = input("> ")
    #     # content = content.split()
    #     print(content)
    
if __name__ == "__main__":
    main(sys.argv)





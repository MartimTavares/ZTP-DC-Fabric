#!/usr/bin/env python
# coding=utf-8

"""
##################################################################################################
## File: configurationless.py
## Author: Martim Carvalhosa Tavares
## Date: 2024-03-05
## Description: A Python script to ...
##################################################################################################
"""

import grpc
import ctypes
import os
import sys
import time
import datetime
import signal
import socket
import json
import threading
import random
import logging
from logging.handlers import RotatingFileHandler
from pygnmi.client import gNMIclient
from ndk import appid_service_pb2
from ndk.sdk_service_pb2_grpc import SdkMgrServiceStub
from ndk.sdk_service_pb2_grpc import SdkNotificationServiceStub
from ndk.sdk_service_pb2 import AgentRegistrationRequest
from ndk.sdk_common_pb2 import SdkMgrStatus
from ndk.sdk_service_pb2 import NotificationRegisterRequest
from ndk.sdk_service_pb2 import NotificationStreamRequest
from ndk.sdk_service_pb2 import Notification
from ndk.sdk_service_pb2 import AppIdRequest
from ndk import interface_service_pb2
from ndk import networkinstance_service_pb2
from ndk import lldp_service_pb2
from ndk import route_service_pb2
from ndk import config_service_pb2
from ndk.config_service_pb2 import ConfigSubscriptionRequest

## - Application name
app_name ='configurationless'
metadata = [('agent_name', app_name)]
## - gRPC channel to the server -> Sdk_mgr gRPC server always listens on port 50053
channel = grpc.insecure_channel('localhost:50053')
## - Client stub for agentRegister and notificationRequests
stub = SdkMgrServiceStub(channel)
## - Client stub for notificationStreamRequests
sub_stub = SdkNotificationServiceStub(channel)


## - GLOBAL VARIABLES
CLONE_NEWNET = 0x40000000
SR_CA = '/ca.pem'
SR_USER = 'admin'
SR_PASSWORD = 'NokiaSrl1!'
GNMI_PORT = '57400'
SDK_MGR_FAILED = 'kSdkMgrFailed'
NOS_TYPE = 'SRLinux'
NEIGHBOR_CHASSIS = 'neighbor_chassis'
NEIGHBOR_INT = 'neighbor_int'
LOCAL_INT = 'local_int'
SYS_NAME = 'sys_name'
UNDERLAY_PROTOCOL = 'IS-IS' # can be changed to OSPFv3
AREA_ID = '49.0001'
ISIS_INSTANCE = 'i1'
ISIS_LEVEL_CAPABILITY = 'L1'

event_types = ['intf', 'nw_inst', 'lldp', 'route', 'cfg']


#####################################################
####     METHODS TO CREATE THE NOTIFICATIONS     ####
#### SUBSCRIPTION UPON DIFFERENT TYPES OF EVENTS ####
def subscribe(stream_id, option):
    op = NotificationRegisterRequest.AddSubscription
    
    if option == 'intf':
        entry = interface_service_pb2.InterfaceSubscriptionRequest()
        request = NotificationRegisterRequest(op=op, stream_id=stream_id, intf=entry)
    elif option == 'nw_inst':
        entry = networkinstance_service_pb2.NetworkInstanceSubscriptionRequest()
        request = NotificationRegisterRequest(op=op, stream_id=stream_id, nw_inst=entry)
    elif option == 'lldp':
        entry = lldp_service_pb2.LldpNeighborSubscriptionRequest()
        request = NotificationRegisterRequest(op=op, stream_id=stream_id, lldp_neighbor=entry)
    elif option == 'route':
        entry = route_service_pb2.IpRouteSubscriptionRequest()
        request = NotificationRegisterRequest(op=op, stream_id=stream_id, route=entry)
    elif option == 'cfg':
        entry = config_service_pb2.ConfigSubscriptionRequest()
        request = NotificationRegisterRequest(op=op, stream_id=stream_id, config=entry)

    subscription_response = stub.NotificationRegister(request=request, metadata=metadata)
    logging.info(f"[STREAM] :: Status of subscription response for {option} is {subscription_response.status}.")


def subscribeNotifications(stream_id):
    if not stream_id:
        logging.info("[STREAM] :: Stream ID not set.")
        return False
    
    for i in range(len(event_types)):
        subscribe(stream_id, event_types[i])


#####################################################
####         AUXILIARY METHODS and classes       ####
def containString(longer_word, smaller_word):
    return smaller_word in longer_word


class State(object):
    def __init__(self):
        self.lldp_neighbors = []
        self.underlay_protocol = ""
        self.net_id = ""
        self.sys_ip = ""
        self.mac = ""

    def __str__(self):
        return str(self.__class__) + ": " + str(self.__dict__)


def binaryToDecimal(binary):
    ## - Convert binary string to decimal integer
    decimal = int(binary, 2)
    return decimal


def macToBits(mac_address:str):
    mac_components = mac_address.split(':')
    binary_components = [bin(int(comp, 16))[2:].zfill(8) for comp in mac_components]
    mac_binary = ''.join(binary_components)
    return mac_binary


def bitsToIpv4(binary):
    ## - Remove the leftmost 24 bits to have only 24
    bit32_binary = binary[24:]
    bit32_binary = "00000000"+bit32_binary
    ## - Split the binary string into four equal parts
    octets = [bit32_binary[i:i+8] for i in range(0, len(bit32_binary), 8)]
    ## - Convert each octet from binary to decimal
    decimal_octets = [binaryToDecimal(octet) for octet in octets]
    ## - Ensuring first byte is between 1 and 223
    del decimal_octets[0]
    first_byte = random.randint(1, 223)
    decimal_octets.insert(0, first_byte)
    ipv4_address = '.'.join(map(str, decimal_octets))
    return ipv4_address


def macToSYSID(mac_address:str):
    # Remove dots from the MAC address
    mac_address = mac_address.replace(':', '')
    # Divide the MAC address into three parts and join them with dots
    sys_id = '.'.join([mac_address[i:i+4] for i in range(0, len(mac_address), 4)])
    return sys_id


#####################################################
####            THE AGENT'S MAIN LOGIC           ####
def handle_LldpNeighborNotification(notification: Notification, state) -> None:
    interface_name = str(notification.key.interface_name)
    system_name = str(notification.data.system_description) 
    if containString(system_name, NOS_TYPE):
        system_name = NOS_TYPE
    else:
        system_name = ""
    source_chassis = str(notification.key.chassis_id)
    port_id = str(notification.data.port_id)
    neighbor = {NEIGHBOR_CHASSIS:source_chassis, SYS_NAME:system_name, NEIGHBOR_INT:port_id, LOCAL_INT: interface_name}
    
    # if TODO -> only accept if it reached a local interface with a transceiver !!!!!!

    ## - Notification is CREATE (value: 0)
    if notification.op == 0:
        logging.info(f"[NEW NEIGHBOR] :: {source_chassis}, {system_name}, {port_id}, {interface_name}")
        state.lldp_neighbors.append(neighbor)
        # TODO logic -> update topology
    ## - Notification is DELETE (value: 2)
    elif notification.op == 2:
        for i in state.lldp_neighbors[:]:
            if i[LOCAL_INT] == neighbor[LOCAL_INT] and i[NEIGHBOR_CHASSIS] == neighbor[NEIGHBOR_CHASSIS]:
                logging.info(f"[REMOVED NEIGHBOR] :: {i[NEIGHBOR_CHASSIS]}, {i[SYS_NAME]}, {i[NEIGHBOR_INT]}, {i[LOCAL_INT]}")
                state.lldp_neighbors.remove(i)
                # TODO logic -> update topology
    ## - Notification is CHANGE (value: 1)
    else:
        pass
        # TODO
    

def handleNotification(notification: Notification, state)-> None:
    #if notification.HasField("config"):
    #    logging.info("Implement config notification handling if needed")
    #if notification.HasField("intf"):
    #    handle_InterfaceNotification(notification.intf)
    #if notification.HasField("nw_inst"):
    #    handle_NetworkInstanceNotification(notification.nw_inst)
    if notification.HasField('lldp_neighbor'):
        handle_LldpNeighborNotification(notification.lldp_neighbor, state)
    #if notification.HasField("route"):
    #    logging.info("Implement route notification handling if needed")
    return False


#####################################################
####       MAIN FUNCTIONS TO INITIALIZE THE      ####
####            AGENT AND THE LOG FILES          ####
def Run(hostname):
    ## - Register Application with the NDK manager
    register_request = AgentRegistrationRequest()
    #register_request.agent_liveliness=10 ## ????
    register_response = stub.AgentRegister(request=register_request, metadata=metadata)
    if register_response.status == SdkMgrStatus.Value(SDK_MGR_FAILED):
        logging.error(f"[REGISTRATION] :: Agent Registration failed with error {register_response.error_str}.")
        return
    else:
        logging.info(f"[REGISTRATION] :: Agent Registration successfuly executed with id {register_response.app_id}.")
    app_id = register_response.app_id
    ## - Stream creation Request
    notification_stream_create_request = NotificationRegisterRequest(op=NotificationRegisterRequest.Create)
    notification_stream_create_response = stub.NotificationRegister(request=notification_stream_create_request, metadata=metadata)
    stream_id = notification_stream_create_response.stream_id 
    
    try:
        ## - Add Notification subscriptions (request for all events)
        subscribeNotifications(stream_id)
        ## - Call server streaming notifications: response is a list of notifications
        ## - Actual streaming of notifications is a task for another service (SdkNotificationService)
        ## - NotificationsStream is a server-side streaming RPC which means that SR Linux (server) will send back multiple event notification responses after getting the agent's (client) request.
        notification_stream_request = NotificationStreamRequest(stream_id=stream_id)
        notification_stream_response = sub_stub.NotificationStream(notification_stream_request, metadata=metadata)
        
        ## - Agent's main logic: upon receiving notifications evolve the system according with the new topology.
        state = State()
        state.underlay_protocol = UNDERLAY_PROTOCOL

        ## - gNMI Server connection variables: default port for gNMI server is 57400
        gnmic_host = (hostname, GNMI_PORT) #172.20.20.11, 'clab-dc1-leaf1'
        with gNMIclient(target=gnmic_host, path_cert=SR_CA, username=SR_USER, password=SR_PASSWORD, debug=True) as gc:
            ## - Initial Router ID; IP, NET; int system0 and routing-policy configurations
            result = gc.get(path=["/platform/chassis/hw-mac-address"], encoding="json_ietf")
            #for e in [e for i in result['notification'] if 'update' in i.keys() for e in i['update'] if 'val' in e.keys()]:
            sys_mac = result['notification'][0]['update'][0]['val']
            state.mac = sys_mac
            logging.info('[SYSTEM MAC] :: ' + f'{sys_mac}')

            sys_id = macToSYSID(sys_mac)
            logging.info('[SYSTEM ID] :: ' + f'{sys_id}')
            net_id = AREA_ID + '.' + sys_id + '.00'
            state.net_id = net_id
            logging.info('[NET ID] :: ' + f'{net_id}')

            router_id_ipv4 = bitsToIpv4(macToBits(sys_mac))
            sys0_conf = {
                        'subinterface' : [
                            {
                            'index' : '0',
                            # /interface[name=system]/subinterface[index=0]
                            'ipv4' : {
                                'address' : [
                                    {'ip-prefix' : f'{router_id_ipv4}/32'}
                                ],
                                'admin-state' : 'enable'
                            }, 
                            'admin-state' : 'enable'
                            #
                            }
                        ],
                        'admin-state' : 'enable'
                        } 
            net_inst = {
                       'admin-state' : 'enable',
                       'interface' : [
                           {'name' : 'system0.0'}
                       ]  
                       }
            updates = [
                ('/network-instance[name=default]', net_inst),
                ('/interface[name=system0]', sys0_conf)
            ] 
            result = gc.set(update=updates, encoding="json_ietf")
            logging.info('[gNMIc] :: ' + f'{result}')
            for conf in result['response']:
                if str(conf['path']) == 'interface[name=system0]':
                    logging.info('[SYSTEM IP] :: ' + f'{router_id_ipv4}')

            routing_policy = { 'default-action' : {'policy-result' : 'accept'} }
            update = [ ('/routing-policy/policy[name=all]', routing_policy)]
            result = gc.set(update=update, encoding="json_ietf")
            logging.info('[gNMIc] :: ' + f'{result}')
            if state.underlay_protocol == 'IS-IS':
                # Configure IS-IS NET ID and system0.0
                instance_isis = {
                                    'instance' : [
                                        {'name' : f'{ISIS_INSTANCE}',
                                         'admin-state' : 'enable',
                                         'level-capability' : f'{ISIS_LEVEL_CAPABILITY}',
                                         'net' :  [ {'net' : f'{state.net_id}'} ],
                                         'interface' : [
                                             {'interface-name' : 'system0.0',
                                              'admin-state' : 'enable',
                                              'circuit-type' : 'point-to-point',
                                              'passive' : 'true'
                                             }
                                         ]
                                        }
                                    ]
                                }
                update = [ ('/network-instance[name=default]/protocols/isis', instance_isis) ]
                result = gc.set(update=update, encoding="json_ietf")
                logging.info('[gNMIc] :: ' + f'{result}')
                for conf in result['response']:
                    if str(conf['path']) == '/network-instance[name=default]/protocols/isis':
                        logging.info('[UNDERLAY] :: IS-IS with NET ID' + f'{state.net_id}')

            elif state.underlay_protocol == 'OSPFv3':
                pass #TODO
            
            ## - Thread responsible for checking interfaces with transceivers and enable the routing protocol on those interfaces
            #TODO

            ## - New notifications incoming
            count = 0
            for r in notification_stream_response:
                count += 1
                #logging.info(f"[RECEIVED NOTIFICATION] :: Number {count} \n{r.notification}")
                for obj in r.notification:
                    if obj.HasField('config') and obj.config.key.js_path == ".commit.end":
                        logging.info('[TO DO] :: -commit.end config')
                    else:
                        handleNotification(obj, state)

    except grpc._channel._Rendezvous as err:
        logging.info(f"[EXITING NOW] :: {str(err)}")
    except Exception as e:
        logging.error(f"[EXCEPTION] :: {str(e)}")
        try:
            response = stub.AgentUnRegister(request=AgentRegistrationRequest(), metadata=metadata)
            logging.error(f"[UNREGISTRATION] :: {response}")
        except grpc._channel._Rendezvous as err:
            logging.info(f"[EXITING NOW] :: {str(err)}")
            sys.exit()
        return True
    sys.exit()


def Exit_Gracefully(signum, frame):
    logging.info(f"[SIGNAL CAUGHT] :: {signum}\n will unregister fib_agent.")
    try:
        response=stub.AgentUnRegister(request=AgentRegistrationRequest(), metadata=metadata)
        logging.error(f"[ERROR] :: Unregister response :: {response}.")
        sys.exit()
    except grpc._channel._Rendezvous as err:
        logging.info(f"[EXCEPTION] :: {err}")
        sys.exit()


def initialLoggingSetup(hostname):
    stdout_dir = '/var/log/srlinux/stdout'
    if not os.path.exists(stdout_dir):
        os.makedirs(stdout_dir, exist_ok=True)
    log_filename = '{}/{}_configurationless.log'.format(stdout_dir, hostname)
    logging.basicConfig(filename=log_filename, filemode='a',\
                        format='[%(levelname)s %(asctime)s,%(msecs)d %(name)s]',\
                        datefmt='%H:%M:%S', level=logging.INFO)
    handler = RotatingFileHandler(log_filename, maxBytes=3000000, backupCount=5)
    logging.getLogger().addHandler(handler)
    logging.info("[START TIME] :: {}".format(datetime.datetime.now()))


if __name__ == '__main__':
    ## - Change the network namespace to the approriate one
    ns_path = '/var/run/netns/srbase-mgmt'
    ns_fd = os.open(ns_path, os.O_RDONLY)
    libc = ctypes.CDLL('libc.so.6')
    setns = libc.setns
    setns.argtypes = [ctypes.c_int, ctypes.c_int]
    if setns(ns_fd, CLONE_NEWNET) == -1:
        raise Exception("Failed to set network namespace")

    hostname = socket.gethostname()
    ## - SIGTERM is the signal that is typically used to administratively terminate a process.
    ## - This signal is sent by the process to terminate (gracefully) this process.
    ## - Agent needs to handle SIGTERM signal that is sent when a user invokes stop command via SR Linux CLI.
    signal.signal(signal.SIGTERM, Exit_Gracefully)
    ## - Define path to log file: /var/log/srlinux/stdout
    initialLoggingSetup(hostname)
    ## - Run the function that contains the agent's logic
    if Run(hostname):
        logging.info(f"[REGISTRATION] :: Agent unregistered and routes were withdrawn.")
    else:
        logging.info(f"[EXCEPTION] :: Some exception caught.")




#!/usr/bin/env python
# coding=utf-8

"""
##################################################################################################
## File: configurationless.py
## Author: Martim Carvalhosa Tavares
## Date: 2024-03-05
## Description: A Python script used by a SR Linux NDK agent to optimize the automation in the DC.
##              This optimization makes each SR Linux device able to automatically configure 
##              itself, based on the information regarding its role in the DC topology.
##              Using the information retrieved from LLDP messages, the device enables the underlay
##              routing with the ports connecting to other SR Linux devices. Once the underlay is
##              enabled, it learns the whole network topology and infers the role of each node in
##              order to elect the 2 Route Reflectors, thus setting up the overlay infrastructure.
##################################################################################################
"""
from algorithms.nodesRolesAlgorithm import nodesRolesAlgorithm
import grpc
import ctypes
import os
import sys
import time
import datetime
import signal
import socket
import ipaddress
import json
import threading
import random
import logging
from logging.handlers import RotatingFileHandler
from copy import copy, deepcopy
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
RR_NUMBER = 2
IBGP_ASN = '100'

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
        self.new_lldp_notification = False
        self.isis_nodes = [] #[ {role : leaf, ip_addr : 1.1.1.1, net_id : 49.0001.1A0D.00FF.0000.00, neighbors_ip : [ {ip_addr:2.2.2.2}, ...], neighbors_net_id } ]
        self.underlay_protocol = ""
        self.net_id = ""
        self.sys_ip = ""
        self.mac = ""
        self.route_reflectors = []
        self.leaves = []
        self.spines = []
        self.super_spines = []
        self.borders = []
        self.ibgp = False

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


def fillNodesNeighbors(state):
    ## - Searches over each node's neighbor NET ID and compares with each node's NET ID to retrieve that IP
    for node in state.isis_nodes:
        if len(node['neighbors_ip']) != len(node['neighbors_net_id']):
            node['neighbors_ip'] = []
            for net in node['neighbors_net_id']:
                for other_node in state.isis_nodes:
                    if str(net) == str(other_node['net_id']):
                        node['neighbors_ip'].append(other_node['ip_addr'])
                        break

def orderIPs(ip_list):
    try:
        ip_objects = []
        for ip in ip_list:
            ip_objects.append(ipaddress.ip_address(ip))
        ip_objects.sort()
        return ip_objects
    except ValueError as e:
        logging.info(f"[ERROR] :: Invalid IP address format: {e}")

def delete_ibgp(sys_ip, gnmiclient):
    delete = {
                'admin-state' : 'disable',
                'autonomous-system' : f'{IBGP_ASN}',
                'router-id' : f'{sys_ip}',
                'afi-safi' : [ {
                    'afi-safi-name' : 'evpn',
                    'admin-state' : 'disable'
                }]
            }
    update = [ ('network-instance[name=default]/protocols/bgp', delete) ]
    result = gnmiclient.set(replace=update, encoding="json_ietf")
    for conf in result['response']:
        if str(conf['path']) == '/network-instance[name=default]/protocols/bgp':
            logging.info('[OVERLAY] :: Removed all iBGP configurations')
    

#####################################################
####            THE AGENT'S MAIN LOGIC           ####

def handle_RouteNotification(notification: Notification, state, gnmiclient) -> None:
    node_ip_add = ".".join(str(byte) for byte in notification.key.ip_prefix.ip_addr.addr)
    node_ip_add.split('.')
    notif_ip_addr = str(node_ip_add)
    ## - Check if it is a valid IP address for a node loopback
    if node_ip_add != '0.0.0.0' and 1 <= int(node_ip_add.split('.')[0]) <= 223 and len(node_ip_add.split('.')) == 4:
        state.route_reflectors = []
        if state.underlay_protocol == 'IS-IS':
            ## - Notification is CREATE (value: 0) or UPDATE (value: 1)
            if notification.op == 0 or notification.op == 1:
                ## - Check if IP address is in routing table
                result = gnmiclient.get(path=[f"/network-instance[name=default]/route-table/ipv4-unicast/route[ipv4-prefix=*][route-type=isis][route-owner=isis_mgr][id=0][origin-network-instance=default]/ipv4-prefix"], encoding="json_ietf")
                if 'update' in result['notification'][0]:
                    if result['notification'][0]['update'][0]['val']['route']:
                        for dest in result['notification'][0]['update'][0]['val']['route']:
                            ## - Check if it is a /32 loopback address and if IP is in IS-IS routing tables 
                            if str(dest['ipv4-prefix']) == notif_ip_addr + '/32' and str(dest['route-owner']) == 'isis_mgr':
                                ## - Find and store data about the neighbors of the new IS-IS node with TLVs
                                tlvs = gnmiclient.get(path=[f"network-instance[name=default]/protocols/isis/instance[name={ISIS_INSTANCE}]/level-database[level-number=1][lsp-id=*]/defined-tlvs"], encoding="json_ietf")                             
                                ## - Add information about a new isis node and its neighbors
                                
                                new_isis_node = { 'ip_addr' : notif_ip_addr, 'neighbors_ip' : [], 'neighbors_net_id' : [] }
                                if 'update' in tlvs['notification'][0]:
                                    if tlvs['notification'][0]['update'][0]['val']['level-database']:
                                        for tlv in tlvs['notification'][0]['update'][0]['val']['level-database']:
                                            node_net_id = str(tlv['lsp-id'])[:-3]
                                            node_ip = str(tlv['defined-tlvs']['ipv4-interface-addresses'][0])
                                            
                                            if node_ip == notif_ip_addr:
                                                ## - Creates a new entry for new node joining 
                                                new_isis_node['net_id'] = AREA_ID +'.'+node_net_id
                                                if 'extended-is-reachability' in tlv['defined-tlvs']:
                                                    for neighbor in tlv['defined-tlvs']['extended-is-reachability']:
                                                        ## - Directly connected nodes are at a distance metric of 10
                                                        if neighbor['default-metric'] == 10:
                                                            neighbor_net = AREA_ID+'.'+str(neighbor['neighbor'])
                                                            new_isis_node['neighbors_net_id'].append(neighbor_net)
                                                if notification.op == 1:
                                                    ## - An update on a node means cleaning its existing information and setting new data
                                                    index = ""
                                                    for i in range(len(state.isis_nodes)):
                                                        if state.isis_nodes[i]['ip_addr'] == node_ip:
                                                            index = i
                                                    if index != "":
                                                        state.isis_nodes.pop(index)

                                            else:
                                                if node_ip == state.sys_ip:
                                                    ## - Include the neighbors of this node (me) : updates every time a notif arrives
                                                    i_am_in_list = False
                                                    me_net = AREA_ID +'.'+node_net_id
                                                    me_isis_node = { 'ip_addr' : node_ip, 'net_id' : me_net, 'neighbors_ip' : [], 'neighbors_net_id' : [] }
                                                    for e in state.isis_nodes:
                                                        if e['ip_addr'] == node_ip:
                                                            i_am_in_list = True
                                                            break
                                                    if not i_am_in_list:
                                                        state.isis_nodes.append(me_isis_node)
                                                ## - Besides updating me, it also updates previously joined nodes
                                                ## - Avoiding missing information regarding a node that joins later and connects with a previously known node that is not updated with this new neighbor's NET ID        
                                                for e in state.isis_nodes:
                                                    if e['ip_addr'] == node_ip:
                                                        if 'extended-is-reachability' in tlv['defined-tlvs']:
                                                            e['neighbors_net_id'] = []
                                                            e['neighbors_ip'] = []
                                                            for neighbor in tlv['defined-tlvs']['extended-is-reachability']:
                                                                ## - Directly connected nodes are at a distance metric of 10
                                                                if neighbor['default-metric'] == 10:
                                                                    neighbor_net = AREA_ID+'.'+str(neighbor['neighbor'])
                                                                    if neighbor_net not in e['neighbors_net_id']:
                                                                        e['neighbors_net_id'].append(neighbor_net)
                                
                                state.isis_nodes.append(new_isis_node)
                                fillNodesNeighbors(state)
                                if notification.op == 0:
                                    logging.info(f"[IS-IS] :: Node {notif_ip_addr} joined the network topology")
                                elif notification.op == 1:
                                    logging.info(f"[IS-IS] :: Node {notif_ip_addr} has changed in the topology")
                                break
            ## - Notification is DELETE (value: 2)
            elif notification.op == 2:
                index = ""
                net = ""
                for node in range(len(state.isis_nodes)):
                    if state.isis_nodes[node]['ip_addr'] == notif_ip_addr:
                        index = node
                        net = state.isis_nodes[node]['net_id']
                if index != "":
                    state.isis_nodes.pop(index)
                    logging.info(f"[IS-IS] :: Node {notif_ip_addr} left the network topology")
                    ## - Need to remove this node's IP and NET from other nodes' neighboring information
                    for n in state.isis_nodes:
                        for n_net in n['neighbors_net_id']:
                            if n_net == net:
                                n['neighbors_net_id'].remove(n_net)
                        for n_ip in n['neighbors_ip']:
                            if n_ip == notif_ip_addr:
                                n['neighbors_ip'].remove(n_ip)
        
            #logging.info(f"[IS-IS] :: Updated information regarding each node in the IS-IS topology:\n{json.dumps(state.isis_nodes, indent=4)}")
            
        ## - Order all IP addresses from the IS-IS routing table
        list_ips = []
        for node in range(len(state.isis_nodes)):
            list_ips.append(state.isis_nodes[node]['ip_addr'])
        list_ips = orderIPs(list_ips)

        ## - Create list g with each index corresponding to a node and the value is a list with ids of neighbors. These ids correspond to the index of the list_ips.
        nodes_str = ''
        str_list_ips = ['index_0']
        g = [[0,0]]
        for e in range(len(list_ips)):
            str_list_ips.append(str(list_ips[e]))
        for e in range(len(str_list_ips)):
            for i in range(len(state.isis_nodes)):
                if state.isis_nodes[i]['ip_addr'] == str_list_ips[e]:
                    neighbors = state.isis_nodes[i]['neighbors_ip']
                    nodes_str += str(state.isis_nodes[i]['ip_addr']) + ' : ' + str(neighbors) + '\n'
                    node_neighbors = []
                    for nei in range(len(neighbors)):
                        for l in range(len(str_list_ips)):
                            if neighbors[nei] == str_list_ips[l]:
                                node_neighbors.append(l)
                    g.append(node_neighbors)
        logging.info(f"[IS-IS] :: {datetime.datetime.now()} Updated information on the IS-IS topology:\n{nodes_str}")

        ## - Run the Roles Algorithm: g = [ [0,0], [one node], [needs one more node] ]
        leaves, spines, super_spines, border = [], [], [], []
        leaves_aux, spines_aux, super_spines_aux, border_aux = [], [], [], []
        if len(g) >= 3:
            leaves_aux, spines_aux, super_spines_aux, border_aux = nodesRolesAlgorithm(g)
        
        ## - Convert the IDs in the lists to the IPv4 addresses
        for e in range(len(leaves_aux)):
            leaves.append(str_list_ips[leaves_aux[e]])
        for e in range(len(spines_aux)):
            spines.append(str_list_ips[spines_aux[e]])
        for e in range(len(super_spines_aux)):
            super_spines.append(str_list_ips[super_spines_aux[e]])
        for e in range(len(border_aux)):
            border.append(str_list_ips[border_aux[e]])

        logging.info(f"Leaves: {str(leaves)}\nSpines: {str(spines)}\nSuper-Spines:{str(super_spines)}\nBorder-Leaves:{str(border)}\n")

        ## - Choose 2 Route Reflectors and configure them.
        if (len(leaves) + len(spines) + len(super_spines) + len(border)) > 2:
            ## - Only set a new iBGP configuration if the previously known topology changed.
            if state.leaves != leaves or state.spines != spines or state.super_spines != super_spines or state.borders != border:
                elected_rr = []
                if len(super_spines) > 0:
                    for e in range(len(super_spines)):
                        if len(elected_rr) < RR_NUMBER:
                            elected_rr.append(super_spines[e])
                        else:
                            break
                if len(elected_rr) < RR_NUMBER and len(border) > 0:
                    for e in range(len(border)):
                        if len(elected_rr) < RR_NUMBER:
                            elected_rr.append(border[e])
                        else:
                            break
                if len(elected_rr) < RR_NUMBER and len(spines) > 0:
                    for e in range(len(spines)):
                        if len(elected_rr) < RR_NUMBER:
                            elected_rr.append(spines[e])
                        else:
                            break
                if len(elected_rr) < RR_NUMBER and len(leaves) > 0:
                    for e in range(len(leaves)):
                        if len(elected_rr) < RR_NUMBER:
                            elected_rr.append(leaves[e])
                        else:
                            break
                ## - Only change a RR if it changed.
                logging.info(f"[OVERLAY] :: Elected RRs are {str(elected_rr)}")
                add_rr = []
                remove_rr = []
                for e in range(len(state.route_reflectors)):
                    if state.route_reflectors[e] not in elected_rr:
                        remove_rr.append(state.route_reflectors[e]) 
                for e in range(len(elected_rr)):
                    if elected_rr[e] not in state.route_reflectors:
                        add_rr.append(elected_rr[e]) 

                ## - Set up the overlay infrastructure
                if state.sys_ip in elected_rr or state.sys_ip in leaves:
                    if state.ibgp == True:
                        delete_ibgp(state.sys_ip, gnmiclient)
                        state.ibgp = False
                    overlay = {
                                'admin-state' : 'enable',
                                'autonomous-system' : f'{IBGP_ASN}',
                                'router-id' : f'{state.sys_ip}',
                                'group' : [ {
                                    'group-name' : 'overlay',
                                    'admin-state' : 'enable',
                                    'export-policy' : 'all',
                                    'import-policy' : 'all',
                                    'peer-as' : f'{IBGP_ASN}',
                                    'local-as' : 
                                        { 'as-number' : f'{IBGP_ASN}' }
                                    ,
                                    'afi-safi' : [
                                        {
                                            'afi-safi-name' : 'ipv4-unicast',
                                            'admin-state' : 'disable'
                                        },
                                        {
                                            'afi-safi-name' : 'ipv6-unicast',
                                            'admin-state' : 'disable'
                                        },
                                        {
                                            'afi-safi-name' : 'evpn',
                                            'admin-state' : 'enable'
                                        }
                                    ]
                                }],
                                'afi-safi' : [ {
                                    'afi-safi-name' : 'evpn',
                                    'admin-state' : 'enable'
                                }]
                            }
                    if state.sys_ip in leaves:
                        for l in range(RR_NUMBER):
                            if 'neighbor' not in overlay:
                                overlay['neighbor'] = [ {
                                    'peer-address' : f'{elected_rr[l]}',
                                    'admin-state' : 'enable',
                                    'peer-group' : 'overlay'
                                }]
                            else:
                                overlay['neighbor'].append({
                                    'peer-address' : f'{elected_rr[l]}',
                                    'admin-state' : 'enable',
                                    'peer-group' : 'overlay'
                                })
                    elif state.sys_ip in elected_rr:
                        for group in range(len(overlay['group'])):
                            if overlay['group'][group]['group-name'] == 'overlay':
                                overlay['group'][group]['route-reflector'] = {
                                    'client' : 'true',
                                    #'cluster-id' : f'{state.sys_ip}'
                                    'cluster-id' : f'{str(elected_rr[0])}' #Cluster-id is the same for both RRs
                                }
                        for l in range(len(leaves)):
                            if 'neighbor' not in overlay:
                                overlay['neighbor'] = [ {
                                    'peer-address' : f'{leaves[l]}',
                                    'admin-state' : 'enable',
                                    'peer-group' : 'overlay'
                                }]
                            else:
                                overlay['neighbor'].append({
                                    'peer-address' : f'{leaves[l]}',
                                    'admin-state' : 'enable',
                                    'peer-group' : 'overlay'
                                })

                    update = [ ('/network-instance[name=default]/protocols/bgp', overlay) ]
                    time.sleep(2) # Necessary for the testing environment hypervisor to execute the iBGP configuration with success.
                    result = gnmiclient.set(update=update, encoding="json_ietf")
                    #while True:
                    #    try:
                    #        result = gnmiclient.set(update=update, encoding="json_ietf")
                    #        break
                    #    except Exception as X:
                    #        logging.info(f'[ERROR] :: iBGP was not configured. Agent will try again.')
                    for conf in result['response']:
                        if str(conf['path']) == 'network-instance[name=default]/protocols/bgp':
                            logging.info(f'[OVERLAY] :: {datetime.datetime.now()} iBGP initialized with ASN ' + f'{IBGP_ASN}')
                            state.ibgp = True
                else:
                    ## - Delete any bgp configuration: If no longer is a leaf or a RR.
                    #if state.sys_ip in state.leaves or state.sys_ip in state.route_reflectors:
                    if state.ibgp == True:
                        delete_ibgp(state.sys_ip, gnmiclient)
                        state.ibgp = False

                ## - Update the role of each node
                state.route_reflectors = elected_rr
                state.leaves = leaves
                state.spines = spines
                state.super_pines = super_spines
                state.borders = border
        else:
            if state.ibgp == True:
                delete_ibgp(state.sys_ip, gnmiclient)
                state.ibgp = False


def handle_LldpNeighborNotification(notification: Notification, state, gnmiclient) -> None:
    interface_name = str(notification.key.interface_name)
    system_name = str(notification.data.system_description) 
    if containString(system_name, NOS_TYPE):
        system_name = NOS_TYPE
    else:
        system_name = ""
    source_chassis = str(notification.key.chassis_id)
    port_id = str(notification.data.port_id)
    neighbor = {NEIGHBOR_CHASSIS:source_chassis, SYS_NAME:system_name, NEIGHBOR_INT:port_id, LOCAL_INT: interface_name}
    
    int_conf = {
                'subinterface' : [
                    {
                    'index' : '0',
                    # /interface[name=ethernet-1/49]/subinterface[index=0]
                    'ipv4' : {
                        'unnumbered' : {
                            'admin-state' : 'enable',
                            'interface' : 'system0.0'
                        },
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
                    {'name' : f'{interface_name}.0'}
                ]  
                }
    routing_conf = {}
    if state.underlay_protocol == 'IS-IS':
        # Configure IS-IS interfaces
        instance_isis = {
                            'instance' : [
                                {'name' : f'{ISIS_INSTANCE}',
                                 'interface' : [
                                     {'interface-name' : f'{interface_name}.0',
                                      'admin-state' : 'enable',
                                      'circuit-type' : 'point-to-point'
                                     }
                                 ]
                                }
                            ]
                        }
        routing_conf = instance_isis
    create_updates = []
    delete_updates = []
    
    ## - Notification is CREATE (value: 0)
    if notification.op == 0:
        if state.underlay_protocol == 'IS-IS':
            create_updates = [
                (f'/interface[name={interface_name}]', int_conf),
                ('/network-instance[name=default]', net_inst),
                ('/network-instance[name=default]/protocols/isis', routing_conf)
            ]
        result = gnmiclient.set(update=create_updates, encoding="json_ietf")
        #logging.info('[gNMIc] :: ' + f'{result}')
        logging.info(f"[NEW NEIGHBOR] :: {source_chassis}, {system_name}, {port_id}, {interface_name}")
        state.lldp_neighbors.append(neighbor)
    ## - Notification is DELETE (value: 2)
    elif notification.op == 2:
        for i in state.lldp_neighbors[:]:
            if i[LOCAL_INT] == neighbor[LOCAL_INT] and i[NEIGHBOR_CHASSIS] == neighbor[NEIGHBOR_CHASSIS]:
                #int_conf['admin-state'] = "disable"#!!!
                #int_conf['subinterface'][0]['admin-state'] = "disable"
                #int_conf['subinterface'][0]['ipv4']['admin-state'] = "disable"
                #int_conf['subinterface'][0]['ipv4']['unnumbered']['admin-state'] = "disable"
                routing_conf['instance'][0]['interface'][0]['admin-state'] = "disable"
                delete_updates = [
                    #(f'/interface[name={interface_name}]', int_conf),
                    ('/network-instance[name=default]/protocols/isis', routing_conf)
                ]
                result = gnmiclient.set(update=delete_updates, encoding="json_ietf")
                for conf in result['response']:
                    if str(conf['path']) == f'interface[name={interface_name}]':
                        logging.info(f"[REMOVED NEIGHBOR] :: {i[NEIGHBOR_CHASSIS]}, {i[SYS_NAME]}, {i[NEIGHBOR_INT]}, {i[LOCAL_INT]}")
                        state.lldp_neighbors.remove(i)
                
    ## - Notification is CHANGE (value: 1)
    else:
        logging.info(str(notification))
        pass
        # TODO
    state.new_lldp_notification = True
    

def handleNotification(notification: Notification, state, gnmiclient)-> None:
    if notification.HasField('lldp_neighbor'):
        handle_LldpNeighborNotification(notification.lldp_neighbor, state, gnmiclient)
    if notification.HasField("route"):
        handle_RouteNotification(notification.route, state, gnmiclient)
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
            
            ## - Checking if has any Loopback configuration
            check_ip_exist = gc.get(path=["/interface[name=system0]/subinterface[index=0]/ipv4"], encoding="json_ietf")
            if 'update' in check_ip_exist['notification'][0]:
                if 'address' in check_ip_exist['notification'][0]['update'][0]['val']:
                    if 'ip-prefix' in check_ip_exist['notification'][0]['update'][0]['val']['address'][0]:
                        state.sys_ip = check_ip_exist['notification'][0]['update'][0]['val']['address'][0]['ip-prefix'][:-3]
            ## - Create a Loopback address in case it doesn't exist already
            else:
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
                #logging.info('[gNMIc] :: ' + f'{result}')
                for conf in result['response']:
                    if str(conf['path']) == 'interface[name=system0]':
                        logging.info('[SYSTEM IP] :: ' + f'{router_id_ipv4}')
                state.sys_ip = router_id_ipv4

            routing_policy = { 'default-action' : {'policy-result' : 'accept'} }
            update = [ ('/routing-policy/policy[name=all]', routing_policy)]
            result = gc.set(update=update, encoding="json_ietf")
            #logging.info('[gNMIc] :: ' + f'{result}')
            if state.underlay_protocol == 'IS-IS':
                ## - Configure IS-IS NET ID and system0.0
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
                #logging.info('[gNMIc] :: ' + f'{result}')
                for conf in result['response']:
                    if str(conf['path']) == '/network-instance[name=default]/protocols/isis':
                        logging.info('[UNDERLAY] :: IS-IS with NET ID' + f'{state.net_id}')

            elif state.underlay_protocol == 'OSPFv3':
                pass #TODO

            ## - New notifications incoming
            count = 0
            for r in notification_stream_response:
                count += 1
                for obj in r.notification:
                    if obj.HasField('config') and obj.config.key.js_path == ".commit.end":
                        logging.info('[TO DO] :: -commit.end config')
                    else:
                        handleNotification(obj, state, gc)

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




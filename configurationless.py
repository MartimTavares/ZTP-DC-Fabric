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
import logging
import threading
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
SDK_MGR_FAILED = "kSdkMgrFailed"
NOS_TYPE = "SRLinux"
NEIGHBOR_CHASSIS = 'neighbor_chassis'
NEIGHBOR_INT = 'neighbor_int'
LOCAL_INT = 'local_int'
SYS_NAME = 'sys_name'

event_types = ['intf', 'nw_inst', 'lldp', 'route', 'cfg']
lldp_neighbors = []

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
####              AUXILIARY METHODS              ####
def containString(longer_word, smaller_word):
    return smaller_word in longer_word

#####################################################
####            THE AGENT'S MAIN LOGIC           ####
def handle_LldpNeighborNotification(notification: Notification) -> None:
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
        logging.info(f"[NEW NEIGHBOR] :: {interface_name}, {system_name}, {source_chassis}, {port_id}")
        lldp_neighbors.append(neighbor)
        # TODO logic -> update topology
    ## - Notification is DELETE (value: 2)
    elif notification.op == 2:
        for i in range(len(lldp_neighbors)):
            if lldp_neighbors[i] == neighbor:
                lldp_neighbors.remove(lldp_neighbors[i])
                # TODO logic -> update topology
    ## - Notification is CHANGE (value: 1)
    else:
        pass
        # TODO
    
def handleNotification(notification: Notification)-> None:
    #if notification.HasField("config"):
    #    logging.info("Implement config notification handling if needed")
    #if notification.HasField("intf"):
    #    handle_InterfaceNotification(notification.intf)
    #if notification.HasField("nw_inst"):
    #    handle_NetworkInstanceNotification(notification.nw_inst)
    if notification.HasField('lldp_neighbor'):
        handle_LldpNeighborNotification(notification.lldp_neighbor)
    #if notification.HasField("route"):
    #    logging.info("Implement route notification handling if needed")
    return False

def Run():
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
        count = 0
        for r in notification_stream_response:
            count += 1
            logging.info(f"[RECEIVED NOTIFICATION] :: Number {count} \n{r.notification}")
            for obj in r.notification:
                if obj.HasField('config') and obj.config.key.js_path == ".commit.end":
                    logging.info('TO DO -commit.end config')
                else:
                    handleNotification(obj) # may add field 'state'

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
    """
        try:
            for r in notification_stream_response:
                count += 1
                logging.info(f"Count :: {count}  NOTIFICATION:: \n{r.notification}")
                for obj in r.notification:
                    Handle_Notification(obj)

"""
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


#####################################################
####        MAIN FUNCTION TO INITIALIZE THE      ####
####            AGENT AND THE LOG FILES          ####
if __name__ == '__main__':
    hostname = socket.gethostname()
    ## - SIGTERM is the signal that is typically used to administratively terminate a process.
    ## - This signal is sent by the process to terminate (gracefully) this process.
    ## - Agent needs to handle SIGTERM signal that is sent when a user invokes stop command via SR Linux CLI.
    signal.signal(signal.SIGTERM, Exit_Gracefully)
    ## - Define path to log file: /var/log/srlinux/stdout
    initialLoggingSetup(hostname)
    ## - Run the function that contains the agent's logic
    if Run():
        logging.info(f"[REGISTRATION] :: Agent unregistered and routes were withdrawn.")
    else:
        logging.info(f"[EXCEPTION] :: Some exception caught.")




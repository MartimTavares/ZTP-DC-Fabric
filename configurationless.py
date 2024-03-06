#!/usr/bin/env python
# coding=utf-8

"""
#################################################
File: configurationless.py
Author: Martim Carvalhosa Tavares
Date: 2024-03-05
Description: A Python script to ...
#################################################
"""

import grpc
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

## Application name
app_name ='configurationless'
metadata = [('agent_name', app_name)]
## gRPC channel to the server -> Sdk_mgr gRPC server always listens on port 50053
channel = grpc.insecure_channel('localhost:50053')
## client stub for agentRegister and notificationRequests
stub = SdkMgrServiceStub(channel)
##  client stub for notificationStreamRequests
sub_stub = SdkNotificationServiceStub(channel)

## GLOBAL VARIABLES
SDK_MGR_FAILED = "kSdkMgrFailed"
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
    if stream_id is not None:
        logging.info("[STREAM] :: Stream ID not set.")
        return False
    
    for i in range(len(event_types)):
        subscribe(stream_id, event_types[i])

#####################################################
####            THE AGENT'S MAIN LOGIC           ####
def Run():

    ## Register Application
    register_request = AgentRegistrationRequest()
    register_request.agent_liveliness=10 ## ????
    register_response = stub.AgentRegister(request=register_request, metadata=metadata)
    if register_response.status == SdkMgrStatus.Value(SDK_MGR_FAILED):
        logging.error(f"[REGISTRATION] :: Agent Registration failed with error {register_response.error_str}.")
        return
    else:
        logging.info(f"[REGISTRATION] :: Agent Registration successfuly executed with id {register_response.app_id}.")
    app_id = register_response.app_id
    ## Stream creation Request
    notification_stream_create_request = NotificationRegisterRequest(op=NotificationRegisterRequest.Create)
    notification_stream_create_response = stub.NotificationRegister(request=notification_stream_create_request, metadata=metadata)
    stream_id = notification_stream_create_response.stream_id if notification_stream_create_response.status != SdkMgrStatus.Value(SDK_MGR_FAILED) else None
    ## Build Notification subscription request for all events
    subscribeNotifications(stream_id)

    #sub_stub = SdkNotificationServiceStub(channel)
    #stream_request = NotificationStreamRequest(stream_id=stream_id)
    #stream_response = sub_stub.NotificationStream(stream_request, metadata=metadata)
    
    #count = 0
    #while True:
    """
        try:
            for r in stream_response:
                count += 1
                logging.info(f"Count :: {count}  NOTIFICATION:: \n{r.notification}")
                for obj in r.notification:
                    Handle_Notification(obj)
        except grpc._channel._Rendezvous as err:
            logging.info('GOING TO EXIT NOW: {}'.format(str(err)))
        except Exception as e:
            logging.error('Exception caught :: {}'.format(str(e)))
            try:
                response = stub.AgentUnRegister(request=AgentRegistrationRequest(), metadata=metadata)
                logging.error('Run try: Unregister response:: {}'.format(response))
            except grpc._channel._Rendezvous as err:
                logging.info('GOING TO EXIT NOW: {}'.format(str(err)))
                sys.exit()
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
                        format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',\
                        datefmt='%H:%M:%S', level=logging.INFO)
    handler = RotatingFileHandler(log_filename, maxBytes=3000000, backupCount=5)
    logging.getLogger().addHandler(handler)
    logging.info("[START TIME] :: {}".format(datetime.datetime.now()))

#####################################################
####        MAIN FUNCTION TO INITIALIZE THE      ####
####            AGENT AND THE LOG FILES          ####
if __name__ == '__main__':
    hostname = socket.gethostname()
    ## SIGTERM is the signal that is typically used to administratively terminate a process.
    ## This signal is sent by the process to terminate (gracefully) this process.
    signal.signal(signal.SIGTERM, Exit_Gracefully)
    ## Define path to log file: /var/log/srlinux/stdout
    initialLoggingSetup(hostname)
    ## Run the function that contains the agent's logic
    if Run():
        logging.info(f"[REGISTRATION] :: Agent unregistered and routes were withdrawn.")
    else:
        logging.info(f"[EXCEPTION] :: Some exception caught.")




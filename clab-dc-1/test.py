from pygnmi.client import gNMIclient

with gNMIclient(target=('clab-dc1-leaf1','57400'), path_cert='/home/nokia/Desktop/martim/Configurationless-DC-Fabric/clab-dc-1/clab-dc1/.tls/ca/ca.pem', username='admin', password='NokiaSrl1!', debug=True) as gc:
	result = gc.capabilities()
	result = gc.get(path=["/system/name/host-name"], encoding="json_ietf")
#	print(f'[gNMI SERVER] :: {str(result)}')

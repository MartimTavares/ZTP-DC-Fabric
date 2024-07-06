# Configurationless-DC-Fabric
[Build data and AI skills with DataCamp](https://www.datacamp.com)
## Agent's Files
The following files are used to deploy and execute the ConfigurationLess agent:

- YAML file `configurationless.yml` is used to describe where SR Linux can find the bash file that executes the agent and the YANG file that describes some configurable data used by the agent.

- Bash file `configurationless.sh` installs all required libraries, packages and runs the Python script which holds the agent's logic.

- Python script `configurationless.py` contains the main logic used by the agent to retrieve data and trigger its configuration mechanisms.

- Python script `nodesRolesAlgorithm.py` contains the algorithm used to infer the layer to each node belongs to, based on the network's adjacency informations.

- Python plugin `show-fabric-plugin.py` is the plugin used to set on SR Linux, in order to monitor the agent's execution through the device's CLI.

- YANG file `configurationless.yang` describes the data model used to parse a configuration into the SR Linux.

## How to Use the Testing Environment?
The agent was developed to execute inside a SR Linux device. In order to test it in an emulated environment, it can be used *Containerlab*, which lab scenarios (1-pod and 2-pod) are provided in this repository. The scenario labs are stored in `containerlab/` where `clab-dc-1-pod` contains a network topology made of 1 pod with 3 spines and `clab-dc-2-pod` contains a 2-pod topology with a total of 19 nodes. To execute the test you can use the following commands, inside this repository:
```
[root@nokia Configurationless-DC-Fabric]# cd containerlab/clab-dc-1-pod/
[root@nokia clab-dc-1-pod]# containerlab deploy --reconfigure -t dc1pod.clab.yml
```
Once Containerlab has deployed every device in the network, each one of them can be accessed through a `ssh` session or via `docker exec` since Containerlab uses Docker as the backbone.
```
[root@nokia clab-dc-1-pod]# docker exec -it clab-containerlabName-nodeName sr_cli
```

In order to check that the agent is running inside the SR Linux device, you can use the following command:
```
A:leaf1# show system application configurationless
  +-------------------+------+---------+---------+--------------------------+
  |       Name        | PID  |  State  | Version |       Last Change        |
  +===================+======+=========+=========+==========================+
  | configurationless | 1699 | running |         | 2024-07-06T14:16:19.201Z |
  +-------------------+------+---------+---------+--------------------------+
--{ + running }--[  ]--
A:leaf1#
```

If you want to monitor the agent to check if it is performing well or just to check what is the current inferred topology by each device, you can use the developped command (`show-fabric-plugin.py` file):
```
A:leaf1# show fabric summary
DC fabric with 10 routing devices in the topology
+-----------------+--------------+----------+
|     System IP   | Fabric Layer | RR (Y/n) |
+=================+==============+==========+
| 53.255.0.0      | LEAF         | no       |
| 87.255.0.0      | LEAF         | no       |
| 111.255.0.0     | LEAF         | no       |
| 135.255.0.0     | LEAF         | no       |
| 153.255.0.0     | LEAF         | no       |
| 170.255.0.0     | LEAF         | no       |
| 195.255.0.0     | LEAF         | no       |
| 159.255.0.0     | SPINE        | YES      |
| 173.255.0.0     | SPINE        | YES      |
| 215.255.0.0     | SPINE        | no       |
+-----------------+--------------+----------+
---------------------------------------------------------------------------------------------------------------------------------------------------------
Summary: Fabric Layers Report
---------------------------------------------------------------------------------------------------------------------------------------------------------
--{ + running }--[  ]--
A:leaf1#
```

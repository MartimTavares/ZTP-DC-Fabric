#!/bin/bash

_term (){
    echo "Caugth signal SIGTERM !! "
    kill -TERM "$child" 2>/dev/null
}

function main() {
    trap _term SIGTERM
    local virtual_env="/etc/opt/srlinux/appmgr/venv-dev/bin/activate"
    local main_module="/etc/opt/srlinux/appmgr/user_agents/configurationless.py"

    # source the virtual-environment, which is used to ensure the correct python packages are installed,
    # and the correct python version is used
    # ACTIVATE THE GNMI SERVER
    #sr_cli --candidate-mode --commit-at-end system gnmi-server admin-state enable
    #sr_cli --candidate-mode --commit-at-end system gnmi-server unix-socket admin-state enable
    sr_cli --candidate-mode --commit-at-end system dns server-list '[ 8.8.8.8 ]' network-instance mgmt
    
    python3 -m venv /etc/opt/srlinux/appmgr/venv-dev
    source "${virtual_env}"
    ip netns exec srbase-mgmt pip3 install -U pip setuptools
    ip netns exec srbase-mgmt pip3 install srlinux-ndk
    ip netns exec srbase-mgmt pip3 install 'protobuf>3.20'

    sr_cli --candidate-mode acl cpm-filter ipv4-filter entry 1 match protocol tcp
    sr_cli --candidate-mode --commit-at-end acl cpm-filter ipv4-filter entry 1 action accept 

    export PYTHONPATH="$PYTHONPATH:/etc/opt/srlinux/appmgr/user_agents:/opt/srlinux/bin:/etc/opt/srlinux/appmgr/venv-dev/lib/python3.6/site-packages"
    export http_proxy=""
    export https_proxy=""
    python3 ${main_module}
   
    child=$! 
    wait "$child"

}

main "$@"

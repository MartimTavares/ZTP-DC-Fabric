from srlinux.data import ColumnFormatter, TagValueFormatter, Border, Data, Borders, Alignment
from srlinux.mgmt.cli import CliPlugin
from srlinux.schema import FixedSchemaRoot
from srlinux.syntax import Syntax
from srlinux.location import build_path
from datetime import datetime
import ast

class Plugin(CliPlugin):
    
    def load(self, cli, **_kwargs):
        fabric = cli.show_mode.add_command(Syntax('fabric', help='Shows fabric layers (e.g. leaves, spines)'))
        summary = fabric.add_command(Syntax('summary', help='shows leaves, spines, super-spines and border-leaves in the topology'), update_location=False, callback=self._show_summary, schema=self._get_schema())

    def _show_summary(self, state, output, **_kwargs):
        header = f'Fabric Layers Report'
        result_header = self._populate_header(header)
        self._set_formatters_header(result_header)
        self._show_platform(state,output)
        output.print_data(result_header)

    def _get_schema(self):
        root = FixedSchemaRoot()
        platform_header = root.add_child(
            'platform_header',
            fields=['platform']
        )
        platform_header.add_child(
            'platform_child',
            key='   System IP   ',
            fields=['Fabric Layer','RR (Y/n)']
        )
        return root

    ## - Platform Schema
    def _show_platform(self, state, output, **_kwargs):
        result_platform = Data(self._get_schema())
        self._set_formatters_platform(result_platform)
        with output.stream_data(result_platform):   
          self._populate_data_platform(result_platform, state)
    
    def _set_formatters_platform(self, data):
        data.set_formatter('/platform_header/platform_child', ColumnFormatter()) 
    
    def _populate_data_platform(self, result, state):                   
        result.synchronizer.flush_fields(result)
        data = result.platform_header.create()
        server_data = self._fetch_state_platform(state)
        
        system_ip = self.system_data.system.get().name.get().host_name or '<Unknown>'
        ctrl, leaves, spines, super_spines, border_leaves, rr = self._fetch_data_from_logs(system_ip)
        if ctrl:
            print(f"DC fabric with {len(leaves)+len(spines)+len(super_spines)+len(border_leaves)} routing devices in the zero-touch provisioning topology")  
            for i in range(0, len(leaves)):
                data_child = data.platform_child.create(str(leaves[i]))
                data_child.fabric_layer = "LEAF"
                if leaves[i] in rr:
                    data_child.rr__y_n_ = "YES"
                else:
                    data_child.rr__y_n_ = "no"
                data_child.synchronizer.flush_fields(data_child)
            for i in range(0, len(spines)):
                data_child = data.platform_child.create(str(spines[i]))
                data_child.fabric_layer = "SPINE"
                if spines[i] in rr:
                    data_child.rr__y_n_ = "YES"
                else:
                    data_child.rr__y_n_ = "no"
                data_child.synchronizer.flush_fields(data_child)
            for i in range(0, len(super_spines)):
                data_child = data.platform_child.create(str(super_spines[i]))
                data_child.fabric_layer = "SUPER-SPINE"
                if super_spines[i] in rr:
                    data_child.rr__y_n_ = "YES"
                else:
                    data_child.rr__y_n_ = "no"
                data_child.synchronizer.flush_fields(data_child)
            for i in range(0, len(border_leaves)):
                data_child = data.platform_child.create(str(border_leaves[i]))
                data_child.fabric_layer = "SUPER-SPINE"
                if border_leaves[i] in rr:
                    data_child.rr__y_n_ = "YES"
                else:
                    data_child.rr__y_n_ = "no"
                data_child.synchronizer.flush_fields(data_child)
        else:
            print(f"DC fabric with 0 routing devices in the zero-touch provisioning topology")  
        result.synchronizer.flush_children(result.platform_header)
        return result

    def _fetch_state_platform(self, state):
        system_path = build_path(f'/system/name/host-name')
        self.system_data = state.server_data_store.stream_data(system_path, recursive=True)

    def _fetch_data_from_logs(self, node):
        ctrl = True
        leaves_line = None
        spines_line = None
        super_spines_line = None
        border_leaves_line = None
        rr_line = None
        count = 0
        file_path = f"var/log/srlinux/stdout/{node}_configurationless.log"
        try:
            with open(file_path, 'r') as file:
                for line in file:
                    if count == 1:
                        spines_line = ast.literal_eval(line[len("Spines: "):].strip())
                        count = 2
                    elif count == 2:
                        super_spines_line = ast.literal_eval(line[len("Super-Spines: "):].strip())
                        count = 3
                    elif count == 3:
                        border_leaves_line = ast.literal_eval(line[len("Border-Leaves: "):].strip())
                        count = 0
                    if line.startswith("Leaves"):
                        leaves_line = ast.literal_eval(line[len("Leaves: "):].strip())  # Update leaves_line if it starts with "Leaves"
                        count = 1
                    elif line.startswith("[OVERLAY] :: Elected RRs are"):
                        rr_line = ast.literal_eval(line[len("[OVERLAY] :: Elected RRs are "):].strip())
        except:
            ctrl = False
        return ctrl, leaves_line, spines_line, super_spines_line, border_leaves_line, rr_line
    

    ## - Header Schema
    def _populate_header(self, header):
        result_header = Data(self._get_header_schema())
        data = result_header.header.create()
        data.summary = header
        return result_header

    def _get_header_schema(self):
        root = FixedSchemaRoot()
        root.add_child(
            'header',
            fields=['Summary']
        )
        return root

    def _set_formatters_header(self, data):
        data.set_formatter('/header',Border(TagValueFormatter())) 
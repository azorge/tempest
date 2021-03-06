# Copyright (c) 2015 Hewlett-Packard Development Company, L.P.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

import base64
import socket
import struct
import textwrap

import six
from six.moves.urllib import parse as urlparse

from oslo_log import log as logging
from oslo_utils import excutils

from tempest.common import fixed_network
from tempest.common import waiters
from tempest import config
from tempest.lib.common import rest_client
from tempest.lib.common.utils import data_utils

if six.PY2:
    ord_func = ord
else:
    ord_func = int

CONF = config.CONF

LOG = logging.getLogger(__name__)


def create_test_server(clients, validatable=False, validation_resources=None,
                       tenant_network=None, wait_until=None,
                       volume_backed=False, name=None, flavor=None,
                       image_id=None, **kwargs):
    """Common wrapper utility returning a test server.

    This method is a common wrapper returning a test server that can be
    pingable or sshable.

    :param clients: Client manager which provides OpenStack Tempest clients.
    :param validatable: Whether the server will be pingable or sshable.
    :param validation_resources: Resources created for the connection to the
        server. Include a keypair, a security group and an IP.
    :param tenant_network: Tenant network to be used for creating a server.
    :param wait_until: Server status to wait for the server to reach after
        its creation.
    :param volume_backed: Whether the server is volume backed or not.
                          If this is true, a volume will be created and
                          create server will be requested with
                          'block_device_mapping_v2' populated with below
                          values:
                          --------------------------------------------
                          bd_map_v2 = [{
                              'uuid': volume['volume']['id'],
                              'source_type': 'volume',
                              'destination_type': 'volume',
                              'boot_index': 0,
                              'delete_on_termination': True}]
                          kwargs['block_device_mapping_v2'] = bd_map_v2
                          ---------------------------------------------
                          If server needs to be booted from volume with other
                          combination of bdm inputs than mentioned above, then
                          pass the bdm inputs explicitly as kwargs and image_id
                          as empty string ('').
    :param name: Name of the server to be provisioned. If not defined a random
        string ending with '-instance' will be generated.
    :param flavor: Flavor of the server to be provisioned. If not defined,
        CONF.compute.flavor_ref will be used instead.
    :param image_id: ID of the image to be used to provision the server. If not
        defined, CONF.compute.image_ref will be used instead.
    :returns: a tuple
    """

    # TODO(jlanoux) add support of wait_until PINGABLE/SSHABLE

    if name is None:
        name = data_utils.rand_name(__name__ + "-instance")
    if flavor is None:
        flavor = CONF.compute.flavor_ref
    if image_id is None:
        image_id = CONF.compute.image_ref

    kwargs = fixed_network.set_networks_kwarg(
        tenant_network, kwargs) or {}

    multiple_create_request = (max(kwargs.get('min_count', 0),
                                   kwargs.get('max_count', 0)) > 1)

    if CONF.validation.run_validation and validatable:
        # As a first implementation, multiple pingable or sshable servers will
        # not be supported
        if multiple_create_request:
            msg = ("Multiple pingable or sshable servers not supported at "
                   "this stage.")
            raise ValueError(msg)

        if 'security_groups' in kwargs:
            kwargs['security_groups'].append(
                {'name': validation_resources['security_group']['name']})
        else:
            try:
                kwargs['security_groups'] = [
                    {'name': validation_resources['security_group']['name']}]
            except KeyError:
                LOG.debug("No security group provided.")

        if 'key_name' not in kwargs:
            try:
                kwargs['key_name'] = validation_resources['keypair']['name']
            except KeyError:
                LOG.debug("No key provided.")

        if CONF.validation.connect_method == 'floating':
            if wait_until is None:
                wait_until = 'ACTIVE'

        if 'user_data' not in kwargs:
            # If nothing overrides the default user data script then run
            # a simple script on the host to print networking info. This is
            # to aid in debugging ssh failures.
            script = '''
                     #!/bin/sh
                     echo "Printing {user} user authorized keys"
                     cat ~{user}/.ssh/authorized_keys || true
                     '''.format(user=CONF.validation.image_ssh_user)
            script_clean = textwrap.dedent(script).lstrip().encode('utf8')
            script_b64 = base64.b64encode(script_clean)
            kwargs['user_data'] = script_b64

    if volume_backed:
        volume_name = data_utils.rand_name(__name__ + '-volume')
        volumes_client = clients.volumes_v2_client
        params = {'name': volume_name,
                  'imageRef': image_id,
                  'size': CONF.volume.volume_size}
        volume = volumes_client.create_volume(**params)
        waiters.wait_for_volume_resource_status(volumes_client,
                                                volume['volume']['id'],
                                                'available')

        bd_map_v2 = [{
            'uuid': volume['volume']['id'],
            'source_type': 'volume',
            'destination_type': 'volume',
            'boot_index': 0,
            'delete_on_termination': True}]
        kwargs['block_device_mapping_v2'] = bd_map_v2

        # Since this is boot from volume an image does not need
        # to be specified.
        image_id = ''

    body = clients.servers_client.create_server(name=name, imageRef=image_id,
                                                flavorRef=flavor,
                                                **kwargs)

    # handle the case of multiple servers
    if multiple_create_request:
        # Get servers created which name match with name param.
        body_servers = clients.servers_client.list_servers()
        servers = \
            [s for s in body_servers['servers'] if s['name'].startswith(name)]
    else:
        body = rest_client.ResponseBody(body.response, body['server'])
        servers = [body]

    # The name of the method to associate a floating IP to as server is too
    # long for PEP8 compliance so:
    assoc = clients.compute_floating_ips_client.associate_floating_ip_to_server

    if wait_until:
        for server in servers:
            try:
                waiters.wait_for_server_status(
                    clients.servers_client, server['id'], wait_until)

                # Multiple validatable servers are not supported for now. Their
                # creation will fail with the condition above (l.58).
                if CONF.validation.run_validation and validatable:
                    if CONF.validation.connect_method == 'floating':
                        assoc(floating_ip=validation_resources[
                              'floating_ip']['ip'],
                              server_id=servers[0]['id'])

            except Exception:
                with excutils.save_and_reraise_exception():
                    for server in servers:
                        try:
                            clients.servers_client.delete_server(
                                server['id'])
                        except Exception:
                            LOG.exception('Deleting server %s failed',
                                          server['id'])

    return body, servers


def shelve_server(servers_client, server_id, force_shelve_offload=False):
    """Common wrapper utility to shelve server.

    This method is a common wrapper to make server in 'SHELVED'
    or 'SHELVED_OFFLOADED' state.

    :param servers_clients: Compute servers client instance.
    :param server_id: Server to make in shelve state
    :param force_shelve_offload: Forcefully offload shelve server if it
                                 is configured not to offload server
                                 automatically after offload time.
    """
    servers_client.shelve_server(server_id)

    offload_time = CONF.compute.shelved_offload_time
    if offload_time >= 0:
        waiters.wait_for_server_status(servers_client, server_id,
                                       'SHELVED_OFFLOADED',
                                       extra_timeout=offload_time)
    else:
        waiters.wait_for_server_status(servers_client, server_id, 'SHELVED')
        if force_shelve_offload:
            servers_client.shelve_offload_server(server_id)
            waiters.wait_for_server_status(servers_client, server_id,
                                           'SHELVED_OFFLOADED')


def create_websocket(url):
    url = urlparse.urlparse(url)
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    client_socket.connect((url.hostname, url.port))
    # Turn the Socket into a WebSocket to do the communication
    return _WebSocket(client_socket, url)


class _WebSocket(object):
    def __init__(self, client_socket, url):
        """Contructor for the WebSocket wrapper to the socket."""
        self._socket = client_socket
        # Upgrade the HTTP connection to a WebSocket
        self._upgrade(url)

    def receive_frame(self):
        """Wrapper for receiving data to parse the WebSocket frame format"""
        # We need to loop until we either get some bytes back in the frame
        # or no data was received (meaning the socket was closed).  This is
        # done to handle the case where we get back some empty frames
        while True:
            header = self._socket.recv(2)
            # If we didn't receive any data, just return None
            if len(header) == 0:
                return None
            # We will make the assumption that we are only dealing with
            # frames less than 125 bytes here (for the negotiation) and
            # that only the 2nd byte contains the length, and since the
            # server doesn't do masking, we can just read the data length
            if ord_func(header[1]) & 127 > 0:
                return self._socket.recv(ord_func(header[1]) & 127)

    def send_frame(self, data):
        """Wrapper for sending data to add in the WebSocket frame format."""
        frame_bytes = list()
        # For the first byte, want to say we are sending binary data (130)
        frame_bytes.append(130)
        # Only sending negotiation data so don't need to worry about > 125
        # We do need to add the bit that says we are masking the data
        frame_bytes.append(len(data) | 128)
        # We don't really care about providing a random mask for security
        # So we will just hard-code a value since a test program
        mask = [7, 2, 1, 9]
        for i in range(len(mask)):
            frame_bytes.append(mask[i])
        # Mask each of the actual data bytes that we are going to send
        for i in range(len(data)):
            frame_bytes.append(ord_func(data[i]) ^ mask[i % 4])
        # Convert our integer list to a binary array of bytes
        frame_bytes = struct.pack('!%iB' % len(frame_bytes), * frame_bytes)
        self._socket.sendall(frame_bytes)

    def close(self):
        """Helper method to close the connection."""
        # Close down the real socket connection and exit the test program
        if self._socket is not None:
            self._socket.shutdown(1)
            self._socket.close()
            self._socket = None

    def _upgrade(self, url):
        """Upgrade the HTTP connection to a WebSocket and verify."""
        # The real request goes to the /websockify URI always
        reqdata = 'GET /websockify HTTP/1.1\r\n'
        reqdata += 'Host: %s:%s\r\n' % (url.hostname, url.port)
        # Tell the HTTP Server to Upgrade the connection to a WebSocket
        reqdata += 'Upgrade: websocket\r\nConnection: Upgrade\r\n'
        # The token=xxx is sent as a Cookie not in the URI
        reqdata += 'Cookie: %s\r\n' % url.query
        # Use a hard-coded WebSocket key since a test program
        reqdata += 'Sec-WebSocket-Key: x3JJHMbDL1EzLkh9GBhXDw==\r\n'
        reqdata += 'Sec-WebSocket-Version: 13\r\n'
        # We are choosing to use binary even though browser may do Base64
        reqdata += 'Sec-WebSocket-Protocol: binary\r\n\r\n'
        # Send the HTTP GET request and get the response back
        self._socket.sendall(reqdata.encode('utf8'))
        self.response = data = self._socket.recv(4096)
        # Loop through & concatenate all of the data in the response body
        while len(data) > 0 and self.response.find(b'\r\n\r\n') < 0:
            data = self._socket.recv(4096)
            self.response += data

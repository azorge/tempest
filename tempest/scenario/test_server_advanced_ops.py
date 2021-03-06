# Copyright 2012 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from oslo_log import log as logging
import testtools

from tempest.common import waiters
from tempest import config
from tempest.lib import decorators
from tempest.scenario import manager
from tempest import test

CONF = config.CONF

LOG = logging.getLogger(__name__)


class TestServerAdvancedOps(manager.ScenarioTest):

    """The test suite for server advanced operations

    This test case stresses some advanced server instance operations:
     * Resizing a volume-backed instance
     * Sequence suspend resume
    """

    @classmethod
    def setup_credentials(cls):
        cls.set_network_resources()
        super(TestServerAdvancedOps, cls).setup_credentials()

    @test.attr(type='slow')
    @decorators.idempotent_id('e6c28180-7454-4b59-b188-0257af08a63b')
    @testtools.skipUnless(CONF.compute_feature_enabled.resize,
                          'Resize is not available.')
    @testtools.skipUnless(CONF.compute.flavor_ref !=
                          CONF.compute.flavor_ref_alt
                          and CONF.compute.flavor_ref_alt != "",
                          'The flavor_ref_alt option should not be empty and '
                          'should not be identical with flavor_ref')
    @test.services('compute', 'volume')
    def test_resize_volume_backed_server_confirm(self):
        # We create an instance for use in this test
        instance = self.create_server(volume_backed=True)
        instance_id = instance['id']
        resize_flavor = CONF.compute.flavor_ref_alt
        LOG.debug("Resizing instance %s from flavor %s to flavor %s",
                  instance['id'], instance['flavor']['id'], resize_flavor)
        self.servers_client.resize_server(instance_id, resize_flavor)
        waiters.wait_for_server_status(self.servers_client, instance_id,
                                       'VERIFY_RESIZE')

        LOG.debug("Confirming resize of instance %s", instance_id)
        self.servers_client.confirm_resize_server(instance_id)

        waiters.wait_for_server_status(self.servers_client, instance_id,
                                       'ACTIVE')

    @test.attr(type='slow')
    @decorators.idempotent_id('949da7d5-72c8-4808-8802-e3d70df98e2c')
    @testtools.skipUnless(CONF.compute_feature_enabled.suspend,
                          'Suspend is not available.')
    @test.services('compute')
    def test_server_sequence_suspend_resume(self):
        # We create an instance for use in this test
        instance_id = self.create_server()['id']

        for _ in range(2):
            LOG.debug("Suspending instance %s", instance_id)
            self.servers_client.suspend_server(instance_id)
            waiters.wait_for_server_status(self.servers_client, instance_id,
                                           'SUSPENDED')

            LOG.debug("Resuming instance %s", instance_id)
            self.servers_client.resume_server(instance_id)
            waiters.wait_for_server_status(self.servers_client, instance_id,
                                           'ACTIVE')

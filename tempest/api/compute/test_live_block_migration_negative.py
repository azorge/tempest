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

from tempest.api.compute import base
from tempest.common import waiters
from tempest import config
from tempest.lib.common.utils import data_utils
from tempest.lib import decorators
from tempest.lib import exceptions as lib_exc
from tempest import test

CONF = config.CONF


class LiveBlockMigrationNegativeTestJSON(base.BaseV2ComputeAdminTest):
    @classmethod
    def skip_checks(cls):
        super(LiveBlockMigrationNegativeTestJSON, cls).skip_checks()
        if not CONF.compute_feature_enabled.live_migration:
            raise cls.skipException("Live migration is not enabled")

    def _migrate_server_to(self, server_id, dest_host):
        bmflm = CONF.compute_feature_enabled.block_migration_for_live_migration
        self.admin_servers_client.live_migrate_server(
            server_id, host=dest_host, block_migration=bmflm,
            disk_over_commit=False)

    @test.attr(type=['negative'])
    @decorators.idempotent_id('7fb7856e-ae92-44c9-861a-af62d7830bcb')
    def test_invalid_host_for_migration(self):
        # Migrating to an invalid host should not change the status
        target_host = data_utils.rand_name('host')
        server = self.create_test_server(wait_until="ACTIVE")

        self.assertRaises(lib_exc.BadRequest, self._migrate_server_to,
                          server['id'], target_host)
        waiters.wait_for_server_status(self.servers_client, server['id'],
                                       'ACTIVE')

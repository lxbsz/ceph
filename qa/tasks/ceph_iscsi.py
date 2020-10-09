"""
Run ceph-iscsi cluster setup
"""
import logging
import socket
import re
from io import StringIO
from teuthology.exceptions import CommandFailedError
from teuthology.orchestra import run
from textwrap import dedent

log = logging.getLogger(__name__)

class IscsiSetup(object):
    def __init__(self, ctx, config):
        self.ctx = ctx
        self.config = config
        self.target_iqn = "iqn.2003-01.com.redhat.iscsi-gw:ceph-gw"
        self.client_iqn = "iqn.1994-05.com.redhat:client"
        self.trusted_ip_list = []

    # Copied from ceph-iscsi project
    def get_host(self, ip=''):
        """
        If the 'ip' is empty, it will return local node's
        hostname, or will return the specified node's hostname
        """
        return socket.getfqdn(ip)

    # Get the trusted ip list from the ceph.conf
    def _get_trusted_ip_list(self, remote, target):
        if self.trusted_ip_list is not []:
            return
        stdout = StringIO()
        stderr = StringIO()
        try:
            args = ['cat', target]
            remote.run(args=args, stdout=stdout, stderr=stderr)
        except CommandFailedError:
            if "No such file or directory" in stderr.getvalue():
                raise

        ips = re.findall(r'mon host = \[v2:([\d.]+).*v1.*\],\[v2:([\d.]+).*v1.*\],\[v2:([\d.]+).*v1.*\]', stdout.getvalue())
        self.trusted_ip_list = list(ips[0])
        if self.trusted_ip_list is []:
            raise RuntimeError("no trust ip list was found!")

    def _setup_gateway(self, role):
        """Spawned task that setups the gateway"""
        (remote,) = self.ctx.cluster.only(role).remotes.keys()

        # setup the iscsi-gateway.cfg file, we only set the
        # clust_name and trusted_ip_list and all the others
        # as default
        target = "/etc/ceph/ceph.conf"
        self._get_trusted_ip_list(remote, target)

        args = ['sudo', 'echo', 'cluster_name = ceph', run.Raw('>'), target]
        remote.run(args=args)
        args = ['sudo', 'echo', 'pool = rbd', run.Raw('>>'), target]
        remote.run(args=args)
        args = ['sudo', 'echo', 'api_secure = false', run.Raw('>>'), target]
        remote.run(args=args)
        args = ['sudo', 'echo', 'api_port = 5000', run.Raw('>>'), target]
        remote.run(args=args)
        ips = ','.join(self.trusted_ip_list)
        args = ['sudo', 'echo', 'trusted_ip_list = {}'.format(ips), run.Raw('>>'), target]
        remote.run(args=args)

        remote.run(args=['sudo', 'systemctl', 'start', 'tcmu-runner'])
        remote.run(args=['sudo', 'systemctl', 'start', 'rbd-target-gw'])
        remote.run(args=['sudo', 'systemctl', 'start', 'rbd-target-api'])

    def setup_gateways(self):
        for role in self.config['gateways']:
            self._setup_gateway(role)

    def _setup_client(self, role):
        """Spawned task that setups the gateway"""
        (remote,) = self.ctx.cluster.only(role).remotes.keys()

        target = "/etc/iscsi/initiatorname.iscsi"
        remote.run(args=['sudo', 'echo', f'InitiatorName={self.client_iqn}', run.Raw('>'), target]a)
        # the restart is needed after the above change is applied
        remote.run(args=['sudo', 'systemctl', 'restart', 'iscsid'])

        remote.run(args=['sudo', 'modprobe', 'dm_multipath'])
        remote.run(args=['sudo', 'mpathconf', '--enable'])
        conf = dedent('''\
devices {
        device {
                vendor "LIO-ORG"
                user_friendly_names "yes" # names like mpatha
                path_grouping_policy "failover" # one path per group
                hardware_handler "1 alua"
                path_selector "round-robin 0"
                failback immediate
                path_checker "tur"
                prio "alua"
                no_path_retry 120
                rr_weight "uniform"
        }
}
''')
        path = "/etc/multipath.conf"
        remote.sudo_write_file(path, conf, append=True)
        remote.run(args=['sudo', 'systemctl', 'start', 'multipathd'])

    def setup_clients(self):
        for role in self.config['clients']:
            self._setup_client(role)

@contextlib.contextmanager
def task(ctx, config):
    """
    Run fsx on an rbd image.

    Currently this requires running as client.admin
    to create a pool.

    Specify the list of gateways to run ::

      tasks:
        ceph_iscsi:
          gateways: [gateway.0, gateway.1]
          clients: [client.0]

    """
    log.info('setting iscsi cluster...')
    iscsi = IscsiSetup(ctx, config)
    iscsi.setup_gateways()
    iscsi.setup_clients()

    yield

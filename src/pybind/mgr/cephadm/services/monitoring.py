import logging
import os
from typing import List, Any, Tuple, Dict

from orchestrator import DaemonDescription
from cephadm.services.cephadmservice import CephadmService
from mgr_util import verify_tls, ServerConfigException, create_self_signed_cert

logger = logging.getLogger(__name__)

class GrafanaService(CephadmService):
    TYPE = 'grafana'
    DEFAULT_SERVICE_PORT = 3000

    def create(self, daemon_id, host):
        # type: (str, str) -> str
        return self.mgr._create_daemon('grafana', daemon_id, host)

    def generate_config(self):
        # type: () -> Tuple[Dict[str, Any], List[str]]
        deps = []  # type: List[str]

        prom_services = []  # type: List[str]
        for dd in self.mgr.cache.get_daemons_by_service('prometheus'):
            prom_services.append(dd.hostname)
            deps.append(dd.name())
        grafana_data_sources = self.mgr.template.render(
            'services/grafana/ceph-dashboard.yml.j2', {'hosts': prom_services})

        cert = self.mgr.get_store('grafana_crt')
        pkey = self.mgr.get_store('grafana_key')
        if cert and pkey:
            try:
                verify_tls(cert, pkey)
            except ServerConfigException as e:
                logger.warning('Provided grafana TLS certificates invalid: %s', str(e))
                cert, pkey = None, None
        if not (cert and pkey):
            cert, pkey = create_self_signed_cert('Ceph', 'cephadm')
            self.mgr.set_store('grafana_crt', cert)
            self.mgr.set_store('grafana_key', pkey)
            self.mgr.check_mon_command({
                'prefix': 'dashboard set-grafana-api-ssl-verify',
                'value': 'false',
            })

        grafana_ini = self.mgr.template.render(
            'services/grafana/grafana.ini.j2', {'http_port': self.DEFAULT_SERVICE_PORT})

        config_file = {
            'files': {
                "grafana.ini": grafana_ini,
                'provisioning/datasources/ceph-dashboard.yml': grafana_data_sources,
                'certs/cert_file': '# generated by cephadm\n%s' % cert,
                'certs/cert_key': '# generated by cephadm\n%s' % pkey,
            }
        }
        return config_file, sorted(deps)

    def get_active_daemon(self, daemon_descrs: List[DaemonDescription]) -> DaemonDescription:
        # Use the least-created one as the active daemon
        return daemon_descrs[-1]

    def config_dashboard(self, daemon_descrs: List[DaemonDescription]):
        # TODO: signed cert
        dd = self.get_active_daemon(daemon_descrs)
        service_url = 'https://{}:{}'.format(
            self._inventory_get_addr(dd.hostname), self.DEFAULT_SERVICE_PORT)
        self._set_service_url_on_dashboard(
            'Grafana',
            'dashboard get-grafana-api-url',
            'dashboard set-grafana-api-url',
            service_url
        )

class AlertmanagerService(CephadmService):
    TYPE = 'alertmanager'
    DEFAULT_SERVICE_PORT = 9093

    def create(self, daemon_id, host) -> str:
        return self.mgr._create_daemon('alertmanager', daemon_id, host)

    def generate_config(self):
        # type: () -> Tuple[Dict[str, Any], List[str]]
        deps = [] # type: List[str]

        # dashboard(s)
        dashboard_urls = []
        mgr_map = self.mgr.get('mgr_map')
        port = None
        proto = None  # http: or https:
        url = mgr_map.get('services', {}).get('dashboard', None)
        if url:
            dashboard_urls.append(url)
            proto = url.split('/')[0]
            port = url.split('/')[2].split(':')[1]
        # scan all mgrs to generate deps and to get standbys too.
        # assume that they are all on the same port as the active mgr.
        for dd in self.mgr.cache.get_daemons_by_service('mgr'):
            # we consider mgr a dep even if the dashboard is disabled
            # in order to be consistent with _calc_daemon_deps().
            deps.append(dd.name())
            if not port:
                continue
            if dd.daemon_id == self.mgr.get_mgr_id():
                continue
            addr = self.mgr.inventory.get_addr(dd.hostname)
            dashboard_urls.append('%s//%s:%s/' % (proto, addr.split(':')[0],
                                                  port))

        context = {
            'dashboard_urls': dashboard_urls
        }
        yml = self.mgr.template.render('services/alertmanager/alertmanager.yml.j2', context)

        peers = []
        port = '9094'
        for dd in self.mgr.cache.get_daemons_by_service('alertmanager'):
            deps.append(dd.name())
            addr = self.mgr.inventory.get_addr(dd.hostname)
            peers.append(addr.split(':')[0] + ':' + port)
        return {
            "files": {
                "alertmanager.yml": yml
            },
            "peers": peers
        }, sorted(deps)

    def get_active_daemon(self, daemon_descrs: List[DaemonDescription]) -> DaemonDescription:
        # TODO: if there are multiple daemons, who is the active one?
        return daemon_descrs[0]

    def config_dashboard(self, daemon_descrs: List[DaemonDescription]):
        dd = self.get_active_daemon(daemon_descrs)
        service_url = 'http://{}:{}'.format(self._inventory_get_addr(dd.hostname), self.DEFAULT_SERVICE_PORT)
        self._set_service_url_on_dashboard(
            'AlertManager',
            'dashboard get-alertmanager-api-host',
            'dashboard set-alertmanager-api-host',
            service_url
        )


class PrometheusService(CephadmService):
    TYPE = 'prometheus'
    DEFAULT_SERVICE_PORT = 9095

    def create(self, daemon_id, host) -> str:
        return self.mgr._create_daemon('prometheus', daemon_id, host)

    def generate_config(self):
        # type: () -> Tuple[Dict[str, Any], List[str]]
        deps = []  # type: List[str]

        # scrape mgrs
        mgr_scrape_list = []
        mgr_map = self.mgr.get('mgr_map')
        port = None
        t = mgr_map.get('services', {}).get('prometheus', None)
        if t:
            t = t.split('/')[2]
            mgr_scrape_list.append(t)
            port = '9283'
            if ':' in t:
                port = t.split(':')[1]
        # scan all mgrs to generate deps and to get standbys too.
        # assume that they are all on the same port as the active mgr.
        for dd in self.mgr.cache.get_daemons_by_service('mgr'):
            # we consider the mgr a dep even if the prometheus module is
            # disabled in order to be consistent with _calc_daemon_deps().
            deps.append(dd.name())
            if not port:
                continue
            if dd.daemon_id == self.mgr.get_mgr_id():
                continue
            addr = self.mgr.inventory.get_addr(dd.hostname)
            mgr_scrape_list.append(addr.split(':')[0] + ':' + port)

        # scrape node exporters
        nodes = []
        for dd in self.mgr.cache.get_daemons_by_service('node-exporter'):
            deps.append(dd.name())
            addr = self.mgr.inventory.get_addr(dd.hostname)
            nodes.append({
                'hostname': dd.hostname,
                'url': addr.split(':')[0] + ':9100'
            })

        # scrape alert managers
        alertmgr_targets = []
        for dd in self.mgr.cache.get_daemons_by_service('alertmanager'):
            deps.append(dd.name())
            addr = self.mgr.inventory.get_addr(dd.hostname)
            alertmgr_targets.append("'{}:9093'".format(addr.split(':')[0]))

        # generate the prometheus configuration
        context = {
            'alertmgr_targets': alertmgr_targets,
            'mgr_scrape_list': mgr_scrape_list,
            'nodes': nodes,
        }
        r = {
            'files': {
                'prometheus.yml':
                    self.mgr.template.render(
                        'services/prometheus/prometheus.yml.j2', context)
            }
        }

        # include alerts, if present in the container
        if os.path.exists(self.mgr.prometheus_alerts_path):
            with open(self.mgr.prometheus_alerts_path, 'r', encoding='utf-8') as f:
                alerts = f.read()
            r['files']['/etc/prometheus/alerting/ceph_alerts.yml'] = alerts

        return r, sorted(deps)

    def get_active_daemon(self, daemon_descrs: List[DaemonDescription]) -> DaemonDescription:
        # TODO: if there are multiple daemons, who is the active one?
        return daemon_descrs[0]

    def config_dashboard(self, daemon_descrs: List[DaemonDescription]):
        dd = self.get_active_daemon(daemon_descrs)
        service_url = 'http://{}:{}'.format(
            self._inventory_get_addr(dd.hostname), self.DEFAULT_SERVICE_PORT)
        self._set_service_url_on_dashboard(
            'Prometheus',
            'dashboard get-prometheus-api-host',
            'dashboard set-prometheus-api-host',
            service_url
        )

class NodeExporterService(CephadmService):
    TYPE = 'node-exporter'

    def create(self, daemon_id, host) -> str:
        return self.mgr._create_daemon('node-exporter', daemon_id, host)

    def generate_config(self) -> Tuple[Dict[str, Any], List[str]]:
        return {}, []
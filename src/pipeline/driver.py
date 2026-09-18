"""Run a simulation spec end to end with content-hash caching per stage.

Every stage records its input key in state.json; unchanged inputs are skipped
on rerun, so editing the spec's schedule or a profile only redoes what changed.
The compute lock is held for the whole call: one simulation per machine.
"""
import contextlib
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import time
import traceback
import uuid

from src.cad.extract_passage import extract
from src.cad.mesh_regions import mesh as generate_mesh, resolve_sizes
from src.cfd.cht_case import build as build_case
from src.cfd.initialize_velocity import initialize as initialize_velocity
from src.cfd.run_bounded import execute as run_bounded, STOP_STATUSES
from src.cfd.settings import case_settings
from src.cfd.warm_start import seed_temperatures
from src.foam.hashing import digest, content_hash, short
from src.foam.lock import compute_lock
from src.pipeline import spec as spec_module, state as state_module
from src.pipeline.report import write_report
from src.pipeline.status import case_status
from src.results.saved_case import export_saved_case
from src.thermal.materials import material_basis
from src.thermal.operating_screen import screen as operating_screen
from src.verification.audit_fields import audit as audit_fields
from src.verification.audit_geometry import audit as audit_geometry
from src.verification.review_history import review as review_history

SRC = Path(__file__).resolve().parents[1]
STAGES = state_module.STAGES


def source_hash(*names):
    return content_hash({name: digest(SRC / name) for name in names})


class StageFailed(RuntimeError):
    pass


class Driver:
    def __init__(self, root, run, resolved, until=None, log=print):
        self.root, self.run, self.resolved, self.until, self.log = Path(root).resolve(), Path(run).resolve(), resolved, until, log
        self.state = state_module.load(self.run)
        self.state['spec'] = spec_module.describe(resolved)
        (self.run / 'logs').mkdir(parents=True, exist_ok=True)

    # -- stage machinery ----------------------------------------------------
    def stage(self, name, key, work, output=None):
        record = self.state['stages'].setdefault(name, {})
        if record.get('status') == 'done' and record.get('key') == key and (output is None or (self.run / record['output']).exists()):
            record['cached'] = True
            self.log(f'{name:<10} cached  {record.get("output") or ""}')
            return record.get('result')
        record.update(status='running', key=key, cached=False, error=None, started=state_module.now())
        state_module.event(self.state, name, 'running')
        state_module.save(self.run, self.state)
        started = time.monotonic()
        log_path = self.run / 'logs' / f'{name}.log'
        try:
            with log_path.open('a') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                print(f'--- {state_module.now()} {name} key={key[:12]}')
                result = work()
        except Exception as error:
            record.update(status='failed', error=f'{type(error).__name__}: {error}', elapsed_s=round(time.monotonic() - started, 1))
            with log_path.open('a') as log:
                log.write(traceback.format_exc())
            state_module.event(self.state, name, 'failed', record['error'])
            state_module.save(self.run, self.state)
            self.log(f'{name:<10} FAILED  {record["error"]}  (see {log_path.relative_to(self.run)})')
            raise StageFailed(f'{name}: {record["error"]}') from error
        record.update(status='done', elapsed_s=round(time.monotonic() - started, 1), result=result.get('result') if isinstance(result, dict) else None,
                      output=result.get('output') if isinstance(result, dict) else None,
                      summary=result.get('summary') if isinstance(result, dict) else None)
        state_module.event(self.state, name, 'done')
        state_module.save(self.run, self.state)
        self.log(f'{name:<10} done    {record.get("output") or ""}  {json.dumps(record.get("summary") or {})}')
        return record.get('result')

    def relative(self, path):
        return str(Path(path).resolve().relative_to(self.run))

    # -- stages -------------------------------------------------------------
    def stage_handoff(self):
        source = self.resolved['handoff']
        files = sorted(p.name for p in source.iterdir() if p.is_file())
        key = content_hash({name: digest(source / name) for name in files})

        def work():
            target = self.run / 'handoff'
            approved = (source / 'approval.json').is_file()
            if approved:
                from src.requirements.review import verify_handoff
                verify_handoff(source)
            elif not self.resolved['unapproved_handoff_ok']:
                raise ValueError('Handoff has no approval.json; set unapproved_handoff_ok only for synthetic tests')
            else:
                self.state['warnings'].append('Handoff is not user approved (synthetic or test input).')
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
            return {'output': 'handoff', 'summary': {'approved': approved, 'source': str(source)},
                    'result': {'approved': approved}}
        return self.stage('handoff', key, work, output='handoff')

    def stage_geometry(self):
        handoff = self.run / 'handoff'
        key = content_hash({'handoff': self.state['stages']['handoff']['key'], 'source': source_hash('cad/extract_passage.py', 'cad/step_preview.py')})
        output = self.run / 'geometry' / f'geo-{short(key)}'

        def work():
            manifest = extract(handoff, output)
            audit = audit_geometry(handoff, output)
            (output / 'audit.json').write_text(json.dumps(audit, indent=2) + '\n')
            if not audit['geometry_checks_pass']:
                failed = [c['check'] for c in audit['checks'] if c['status'] == 'fail']
                raise ValueError('Geometry audit failed: ' + ', '.join(failed))
            return {'output': self.relative(output), 'result': {'manifest': str(output / 'manifest.json')},
                    'summary': {'fluid_m3': f"{manifest['regions']['fluid']['volume_m3']:.4g}",
                                'heated_m2': f"{manifest['heated_area_m2']:.4g}",
                                'interface_faces': len(manifest['boundary_map']['interface']['occ_surface_tags'])}}
        return self.stage('geometry', key, work, output=str(output.relative_to(self.run)))

    def geometry_manifest(self):
        return json.loads(Path(self.state['stages']['geometry']['result']['manifest']).read_text())

    def stage_mesh(self):
        geometry = Path(self.state['stages']['geometry']['result']['manifest']).parent
        manifest = self.geometry_manifest()
        profile = dict(self.resolved['mesh'])
        name = profile.pop('name')
        settings = resolve_sizes(profile, manifest['port_hydraulic_diameter_m']['inlet'])
        key = content_hash({'geometry': digest(geometry / 'manifest.json'), 'settings': settings, 'source': source_hash('cad/mesh_regions.py')})
        output = self.run / 'mesh' / f'mesh-{short(key)}.msh'

        def work():
            report = generate_mesh(geometry, output, settings)
            return {'output': self.relative(output), 'result': {'mesh': str(output), 'settings': settings, 'profile': name},
                    'summary': {'profile': name, **{k: v for k, v in report['element_counts'].items()},
                                'wall_mm': round(settings['wall_size_m'] * 1000, 3)}}
        return self.stage('mesh', key, work, output=str(output.relative_to(self.run)))

    def stage_materials(self):
        materials = self.resolved['materials']
        inlet = case_settings_temperature(self.resolved['operating'])
        key = content_hash({'materials': materials, 'inlet_K': inlet,
                            'source': source_hash('thermal/materials.py', 'thermal/liquid_water.py', 'thermal/fit_water_transport.py')})
        output = self.run / 'materials' / f'basis-{short(key)}.json'

        def work():
            basis = material_basis(materials['solid'], materials['fluid'], inlet, materials['transport'],
                                   materials.get('fit_range_K'), materials.get('reference_pressure_Pa'))
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(basis, indent=2) + '\n')
            return {'output': self.relative(output), 'result': {'basis': str(output)},
                    'summary': {'solid': basis['solid'], 'fluid': basis['fluid'], 'transport': basis['transport_model'],
                                'rho': round(basis['fluid_properties']['density_kg_m3'], 2)}}
        return self.stage('materials', key, work, output=str(output.relative_to(self.run)))

    def stage_screen(self):
        basis_path = Path(self.state['stages']['materials']['result']['basis'])
        settings = self.case_settings()
        key = content_hash({'basis': digest(basis_path), 'geometry': self.state['stages']['geometry']['key'],
                            'flow': settings['volume_flow_L_min'], 'p': settings['outlet_absolute_pressure_Pa'],
                            'q': settings['heat_flux_W_m2'], 'T': settings['inlet_temperature_K'], 'source': source_hash('thermal/operating_screen.py')})
        output = self.run / 'screen' / f'screen-{short(key)}.json'

        def work():
            project = {'inlet_temperature_K': settings['inlet_temperature_K'], 'heat_flux_W_m2': settings['heat_flux_W_m2'],
                       'outlet_absolute_pressure_bounds_Pa': [settings['outlet_absolute_pressure_Pa']] * 2}
            result = operating_screen(project, self.geometry_manifest(), json.loads(basis_path.read_text()),
                                      [settings['volume_flow_L_min']], settings['minimum_saturation_margin_K'])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2) + '\n')
            row = result['cases'][0]
            if not row['bulk_single_phase_screen_pass']:
                self.state['warnings'].append(f"Bulk outlet temperature {row['bulk_outlet_heat_balance_K']:.1f} K is within "
                                              f"{settings['minimum_saturation_margin_K']} K of saturation; expect the phase screen to fail.")
            return {'output': self.relative(output), 'result': row,
                    'summary': {'heat_W': round(result['heat_input_W'], 1), 'outlet_K': round(row['bulk_outlet_heat_balance_K'], 2),
                                'port_Re': int(row['port_Reynolds']), 'bulk_screen': row['bulk_single_phase_screen_pass']}}
        return self.stage('screen', key, work, output=str(output.relative_to(self.run)))

    def case_settings(self):
        basis = json.loads(Path(self.state['stages']['materials']['result']['basis']).read_text())
        return case_settings(self.resolved['operating'], self.geometry_manifest(), basis, self.resolved['numerics'],
                             self.resolved['schedule']['maximum'])

    def stage_case(self):
        mesh_path = Path(self.state['stages']['mesh']['result']['mesh'])
        basis_path = Path(self.state['stages']['materials']['result']['basis'])
        settings = self.case_settings()
        identity = {k: v for k, v in settings.items() if k != 'iterations'}
        init = self.resolved['initialization']
        key = content_hash({'mesh': digest(mesh_path), 'basis': digest(basis_path), 'settings': identity, 'init': init,
                            'source': source_hash('cfd/cht_case.py', 'cfd/transport.py', 'cfd/turbulence.py', 'cfd/initialize_velocity.py')})
        output = self.run / 'cases' / f'case-{short(key)}'

        def work():
            geometry = Path(self.state['stages']['geometry']['result']['manifest'])
            build_case(output, mesh_path, json.loads(basis_path.read_text()), settings, geometry)
            (output / 'acceptance-criteria.json').write_text(json.dumps(self.resolved['acceptance'], indent=2) + '\n')
            summary = {'numerics': settings['numerics_profile'], 'mass_kg_s': round(settings['mass_flow_kg_s'], 5)}
            if settings.get('velocity_initialization') == 'potential':
                initialize_velocity(output)
                summary['velocity_init'] = 'potential'
            if init.get('temperature_from_case'):
                seed_temperatures(self.root / init['temperature_from_case'], output)
                summary['temperature_init'] = init['temperature_from_case']
            return {'output': self.relative(output), 'result': {'case': str(output)}, 'summary': summary}
        return self.stage('case', key, work, output=str(output.relative_to(self.run)))

    def stage_solve(self):
        case = Path(self.state['stages']['case']['result']['case'])
        schedule = self.resolved['schedule']
        review_path = case / 'bounded-review.json'
        previous = json.loads(review_path.read_text()) if review_path.is_file() else None
        done = previous['chunks'][-1]['iteration'] if previous and previous['chunks'] else 0
        open_ended = previous is None or previous['status'] in ('iteration_limit_not_converged', 'running')
        extend = previous is not None and open_ended and schedule['maximum'] > done
        key = content_hash({'case': self.state['stages']['case']['key'], 'criteria': self.resolved['acceptance'],
                            'maximum': schedule['maximum'] if open_ended else None, 'done': done,
                            'status': previous['status'] if previous else None})

        def work():
            if previous is None or extend:
                review = run_bounded(case, self.resolved['acceptance'], ranks=schedule['ranks'], initial=schedule['initial'],
                                     chunk=schedule['chunk'], maximum=schedule['maximum'], continue_run=previous is not None)
            else:
                review = previous
            last = review['chunks'][-1]
            return {'output': self.relative(case), 'result': {'status': review['status'], 'iteration': last['iteration']},
                    'summary': {'status': review['status'], 'iteration': last['iteration'],
                                'heated_K': round(last['heated_maximum_K'], 2), 'screen': last['numerical_screen_pass']}}
        return self.stage('solve', key, work, output=str(case.relative_to(self.run)))

    def stage_audit(self):
        case = Path(self.state['stages']['case']['result']['case'])
        summary = json.loads((case / 'summary.json').read_text())
        time_name = summary['latest_fields']
        key = content_hash({'summary': digest(case / 'summary.json'), 'source': source_hash('verification/audit_fields.py', 'verification/review_history.py')})
        folder = case / 'audits'

        def work():
            folder.mkdir(exist_ok=True)
            fields = audit_fields(case, case / 'settings.json', case / 'geometry-manifest.json', case / 'acceptance-criteria.json')
            fields_path = folder / f'fields-{time_name}.json'
            fields_path.write_text(json.dumps(fields, indent=2, allow_nan=False) + '\n')
            history = review_history(case, fields_path, case / 'acceptance-criteria.json')
            (folder / f'history-{time_name}.json').write_text(json.dumps(history, indent=2, allow_nan=False) + '\n')
            failed = [c['check'] for c in fields['checks'] + history['checks'] if c['status'] == 'fail']
            return {'output': self.relative(folder), 'result': {'fields': str(fields_path), 'failed': failed,
                                                                 'field_checks_pass': fields['field_checks_pass'],
                                                                 'convergence_checks_pass': history['convergence_checks_pass']},
                    'summary': {'fields': fields['field_checks_pass'], 'history': history['convergence_checks_pass'], 'failed': len(failed)}}
        return self.stage('audit', key, work, output=str(folder.relative_to(self.run)))

    def stage_export(self):
        case = Path(self.state['stages']['case']['result']['case'])
        summary = json.loads((case / 'summary.json').read_text())
        time_name = summary['latest_fields']
        key = content_hash({'summary': digest(case / 'summary.json'), 'source': source_hash('results/saved_case.py', 'results/export.py')})
        output = self.run / 'results-viewer' / f'{case.name}-{time_name}'

        def work():
            export_saved_case(self.run, case.relative_to(self.run).as_posix(), time_name, output)
            return {'output': self.relative(output), 'result': {'viewer': str(output)}, 'summary': {'time': time_name}}
        return self.stage('export', key, work, output=str(output.relative_to(self.run)))

    def collect_result(self):
        case = Path(self.state['stages']['case']['result']['case'])
        manifest = json.loads((case / 'manifest.json').read_text())
        review = json.loads((case / 'bounded-review.json').read_text())
        summary = json.loads((case / 'summary.json').read_text())
        settings = json.loads((case / 'settings.json').read_text())
        last = review['chunks'][-1]
        status = case_status(manifest, review, last)
        audit = self.state['stages'].get('audit', {}).get('result') or {}
        self.state['case'] = {
            'path': self.relative(case), 'status': status['status'], 'stop_reason': review['status'],
            'stop_reason_text': STOP_STATUSES.get(review['status'], ''), 'iteration': last['iteration'],
            'heated_maximum_K': last['heated_maximum_K'], 'heated_maximum_C': last['heated_maximum_K'] - 273.15,
            'temperature_limit_C': settings['temperature_limit_K'] - 273.15,
            'wetted_maximum_C': summary['maximum_wetted_temperature_K'] - 273.15,
            'pressure_drop_bar': summary['pressure_drop_Pa'] / 1e5, 'total_pressure_drop_bar': summary['total_pressure_drop_Pa'] / 1e5,
            'mass_imbalance_fraction': summary['mass_imbalance_fraction'],
            'energy_imbalance_fraction': summary.get('energy_imbalance_with_port_diffusion_fraction'),
            'numerical_checks': last['numerical_checks'], 'phase_screen_pass': last['phase_margin_screen_pass'],
            'audit_failed': audit.get('failed'), 'viewer': self.state['stages'].get('export', {}).get('output'),
        }

    def stage_report(self):
        def work():
            self.collect_result()
            write_report(self.run, self.state, self.resolved)
            return {'output': 'report.md', 'summary': {'status': self.state['case']['status']}}
        return self.stage('report', content_hash({'solve': self.state['stages']['solve'].get('key'), 'audit': self.state['stages'].get('audit', {}).get('key'),
                                                  'source': source_hash('pipeline/report.py')}), work, output='report.md')

    def execute(self):
        order = [('handoff', self.stage_handoff), ('geometry', self.stage_geometry), ('mesh', self.stage_mesh),
                 ('materials', self.stage_materials), ('screen', self.stage_screen), ('case', self.stage_case),
                 ('solve', self.stage_solve), ('audit', self.stage_audit), ('export', self.stage_export), ('report', self.stage_report)]
        for name, method in order:
            method()
            if self.until == name:
                self.log(f'stopped after {name} as requested')
                break
        state_module.save(self.run, self.state)
        return self.state


def case_settings_temperature(operating):
    from src.cfd.settings import temperature_K
    return temperature_K(operating, 'inlet_temperature')


def new_run_directory(root, label):
    import re
    safe = re.sub(r'[^a-zA-Z0-9_-]', '-', label)[:48] or 'run'
    folder = Path(root) / 'runs' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + safe + '-' + uuid.uuid4().hex[:8])
    folder.mkdir(parents=True)
    return folder


def simulate(root, spec_path, run=None, until=None, dry_run=False, log=print):
    """Entry point used by ``workbench simulate``. Returns the run state."""
    root = Path(root).resolve()
    spec = spec_module.load(spec_path)
    resolved = spec_module.resolve(spec, root)
    if dry_run:
        log(json.dumps(spec_module.describe(resolved), indent=2))
        return None
    run = Path(run).resolve() if run else new_run_directory(root, resolved['label'])
    if not run.is_relative_to(root):
        raise ValueError('Run directory must be inside the workspace')
    run.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(spec_path, run / 'spec.json')
    log(f'run: {run.relative_to(root)}')
    with compute_lock(root):
        driver = Driver(root, run, resolved, until=until, log=log)
        try:
            driver.execute()
        except StageFailed:
            pass
        state_module.save(run, driver.state)
    log(state_module.summary_text(driver.state))
    return driver.state

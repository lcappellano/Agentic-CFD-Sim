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
from src.thermal.prescreen import prescreen as run_prescreen, markdown as prescreen_markdown, channel_model, estimate as prescreen_estimate, DEFAULTS as PRESCREEN_DEFAULTS
from src.cfd.settings import pressure_Pa as operating_pressure_Pa
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

    def stage_prescreen(self):
        basis_path = Path(self.state['stages']['materials']['result']['basis'])
        basis = json.loads(basis_path.read_text())
        operating = self.prescreen_operating()
        fixed = self.fixed_operating_point(basis)
        options = self.resolved['prescreen']
        key = content_hash({'basis': digest(basis_path), 'geometry': self.state['stages']['geometry']['key'],
                            'operating': operating, 'fixed': fixed, 'options': options,
                            'source': source_hash('thermal/prescreen.py', 'thermal/saturation.py', 'thermal/autofill.py')})
        output = self.run / 'prescreen' / f'sweep-{short(key)}.json'

        def work():
            result = run_prescreen(self.geometry_manifest(), basis, operating, options, self.resolved.get('handoff_requirements'), fixed)
            table = prescreen_markdown(result, operating)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2, allow_nan=False, default=str) + '\n')
            output.with_suffix('.md').write_text(table)
            self.state['stages']['prescreen']['table'] = table
            for warning in result['warnings']:
                if warning not in self.state['warnings']:
                    self.state['warnings'].append(warning)
            choice = result['autofill']
            summary = {'flows': len(result['rows']), 'pressures': len(result['pressures_Pa'])}
            if choice['volume_flow_L_min'] is not None and choice['outlet_absolute_pressure_Pa'] is not None:
                summary.update(estimate_L_min=float(f"{choice['volume_flow_L_min']:.4g}"),
                               estimate_bar=round(choice['outlet_absolute_pressure_Pa'] / 1e5, 3))
            else:
                summary['estimate'] = 'none'
            return {'output': self.relative(output), 'result': {'autofill': choice, 'table': str(output.with_suffix('.md'))},
                    'summary': summary}
        result = self.stage('prescreen', key, work, output=str(output.relative_to(self.run)))
        table = self.state['stages']['prescreen'].get('table')
        if table:
            self.log(table)
        return result

    def fixed_operating_point(self, basis):
        """Flow (L/min) and outlet pressure (Pa) already fixed by the spec or the review."""
        operating = self.resolved['operating']
        fixed = {}
        if operating.get('mass_flow_kg_s') is not None:
            fixed['volume_flow_L_min'] = operating['mass_flow_kg_s'] / basis['fluid_properties']['density_kg_m3'] * 60000.
        elif operating.get('volume_flow_L_min') is not None:
            fixed['volume_flow_L_min'] = float(operating['volume_flow_L_min'])
        pressure = operating_pressure_Pa(operating, 'outlet_absolute_pressure')
        if pressure is not None:
            fixed['outlet_absolute_pressure_Pa'] = pressure
        return fixed

    def autofill(self, missing):
        """Fill the flow/pressure the spec left open from the prescreen estimate. Returns a prompt
        instead when a human must choose: decision.required, or no feasible estimate."""
        choice = (self.state['stages']['prescreen'].get('result') or {}).get('autofill') or {}
        feasible = choice.get('volume_flow_L_min') is not None and choice.get('outlet_absolute_pressure_Pa') is not None
        estimate = (f" Prescreen estimate: {choice['volume_flow_L_min']:.4g} L/min at "
                    f"{choice['outlet_absolute_pressure_Pa'] / 1e5:.2f} bar absolute." if feasible else '')
        ask = 'Choose the CFD operating point from the prescreen table: set ' + ' and '.join(missing) + ' in the spec.'
        if self.resolved['decision'].get('required'):
            return ask + estimate
        if choice.get('stop') or not feasible:
            return ('The prescreen estimate needs operator input: ' + ' '.join(choice.get('stop') or ['no feasible estimate.']) + estimate
                    + ' ' + ask + ' To run the estimate as it is, copy its values; to let autofill continue past a plausibility '
                    'threshold, raise prescreen.plausible_velocity_m_s / plausible_outlet_pressure_Pa / plausible_pressure_drop_Pa.')
        operating, filled = self.resolved['operating'], {}
        if any(m.startswith('operating.volume_flow') for m in missing):
            operating['volume_flow_L_min'] = filled['volume_flow_L_min'] = float(f"{choice['volume_flow_L_min']:.6g}")
        if any(m.startswith('operating.outlet_absolute_pressure') for m in missing):
            operating['outlet_absolute_pressure_Pa'] = filled['outlet_absolute_pressure_Pa'] = float(choice['outlet_absolute_pressure_Pa'])
        self.state['autofill'] = {'filled': filled, 'reasons': choice['reasons'], 'warnings': choice['warnings'],
                                  'target_temperature_K': choice['target_temperature_K'], 'estimate': choice['estimate'],
                                  'override': 'set these keys in operating, or decision.required: true, to choose yourself'}
        for warning in choice['warnings']:
            note = 'Autofill: ' + warning
            if note not in self.state['warnings']:
                self.state['warnings'].append(note)
        self.state['spec'] = spec_module.describe(self.resolved)
        self.log('autofill   ' + ', '.join(f'{k}={v:.6g}' for k, v in filled.items()) + '  (prescreen estimate; override in operating)')
        return None

    def prescreen_operating(self):
        """Operating values the prescreen needs, with the spec's units normalised."""
        from src.cfd.settings import temperature_K, pressure_Pa
        operating = self.resolved['operating']
        values = {'inlet_temperature_K': temperature_K(operating, 'inlet_temperature'),
                  'temperature_limit_K': temperature_K(operating, 'temperature_limit')}
        if operating.get('heat_flux_W_m2') is not None:
            values['heat_flux_W_m2'] = operating['heat_flux_W_m2']
        elif operating.get('total_heat_load_W') is not None:
            values['heat_flux_W_m2'] = operating['total_heat_load_W'] / self.geometry_manifest()['heated_area_m2']
        else:
            raise ValueError('Provide heat_flux_W_m2 or total_heat_load_W (spec or handoff)')
        for key in ('max_pump_pressure_rise_Pa', 'target_pump_pressure_rise_Pa'):
            if operating.get(key) is not None:
                values[key] = operating[key]
        return values

    def flow_regime(self, basis):
        """Prescreen regime at the chosen operating point: laminar, transitional or turbulent."""
        options = {**PRESCREEN_DEFAULTS, **self.resolved['prescreen']}
        model = channel_model(self.geometry_manifest(), options)
        settings = case_settings(self.resolved['operating'], self.geometry_manifest(), basis, self.resolved['numerics'], 1)
        row = prescreen_estimate(settings['volume_flow_L_min'], model, basis, self.prescreen_operating(), options)
        return row['regime'], row['reynolds']

    def select_numerics(self, basis):
        """Pick laminar or the RANS default from the prescreen regime unless the spec named a profile."""
        regime, reynolds = self.flow_regime(basis)
        current = self.resolved['numerics']['name']
        wanted = 'laminar' if regime == 'laminar' else ('tet-robust' if current == 'laminar' else current)
        note = f'Prescreen regime at the chosen flow: {regime} (Re {reynolds:.0f}).'
        if self.resolved['numerics_explicit']:
            if (regime == 'laminar') != (current == 'laminar'):
                note += f' Spec keeps numerics profile {current}; check the model choice.'
        elif wanted != current:
            self.resolved['numerics'] = spec_module.profile('numerics', wanted)
            note += f' Numerics profile switched to {wanted}.'
        if regime == 'transitional':
            note += ' Transitional flow: neither laminar nor RANS is reliable here.'
        if note not in self.state['warnings']:
            self.state['warnings'].append(note)
        self.state['spec'] = spec_module.describe(self.resolved)

    def prescreen_row(self, basis, settings):
        options = {**PRESCREEN_DEFAULTS, **self.resolved['prescreen']}
        model = channel_model(self.geometry_manifest(), options)
        return prescreen_estimate(settings['volume_flow_L_min'], model, basis, self.prescreen_operating(), options)

    def case_settings(self):
        basis = json.loads(Path(self.state['stages']['materials']['result']['basis']).read_text())
        self.select_numerics(basis)
        settings = case_settings(self.resolved['operating'], self.geometry_manifest(), basis, self.resolved['numerics'],
                                 self.resolved['schedule']['maximum'])
        if self.resolved['initialization'].get('temperature_from_prescreen'):
            row = self.prescreen_row(basis, settings)
            solid_T = row['heated_temperature_K']['spread'] or row['wall_temperature_K']['spread']
            fluid_T = .5 * (settings['inlet_temperature_K'] + row['outlet_temperature_K'])
            settings['initial_temperature_K'] = {'fluid': fluid_T, 'solid': solid_T,
                                                 'source': 'prescreen spread estimate; shortens the pseudo-transient only'}
        return settings

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
        order = [('handoff', self.stage_handoff), ('geometry', self.stage_geometry), ('materials', self.stage_materials),
                 ('prescreen', self.stage_prescreen), ('mesh', self.stage_mesh), ('case', self.stage_case),
                 ('solve', self.stage_solve), ('audit', self.stage_audit), ('export', self.stage_export), ('report', self.stage_report)]
        self.state['status'] = 'running'
        self.state.pop('decision_prompt', None)
        self.state.pop('autofill', None)
        for name, method in order:
            method()
            if name == 'prescreen':
                missing = spec_module.missing_operating_point(self.resolved['operating'])
                prompt = self.autofill(missing) if missing else None
                if prompt:
                    self.state['status'] = 'awaiting_operator_decision'
                    self.state['decision_prompt'] = prompt
                    write_report(self.run, self.state, self.resolved)
                    self.log('stopped: ' + self.state['decision_prompt'])
                    state_module.save(self.run, self.state)
                    return self.state
            if self.until == name:
                self.state['status'] = f'stopped_after_{name}'
                self.log(f'stopped after {name} as requested')
                state_module.save(self.run, self.state)
                return self.state
        self.state['status'] = 'complete'
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
            driver.state['status'] = 'failed'
        state_module.save(run, driver.state)
    log(state_module.summary_text(driver.state))
    return driver.state

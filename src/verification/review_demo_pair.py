"""Apply documented demo criteria to summaries plus independent raw field audits."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from audit_demo_mesh import audit as audit_mesh
from audit_demo_fields import audit as audit_fields
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from src.thermal.demo_estimate import saturation_temperature


def review(run, names):
    checks=[];cases={};inputs={}
    def check(name,ok,evidence):checks.append(dict(check=name,status='pass' if ok else 'fail',evidence=evidence))
    for name in names:
        case=run/name;s=json.loads((case/'summary.json').read_text());m=audit_mesh(case);f=audit_fields(case)
        for p in [case/'summary.json',case/'manifest.json',case/'system/controlDict',case/'system/fluid/fvSchemes',case/'system/solid/fvSchemes',case/'constant/fluid/thermophysicalProperties',case/'constant/solid/thermophysicalProperties',case/'log.solver',case/'log.checkMesh.fluid',case/'log.checkMesh.solid']:
            inputs[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
        inputs.update(m['input_sha256']);inputs.update(f['input_sha256'])
        for k,v in m['checks'].items():check(name+':'+k,v=='pass',m['patches'])
        for key,scalar in [('heated_max_K','heatedMax'),('wetted_max_K','wettedMax')]:
            check(name+':independent_'+key,abs(f[key]-s['monitor_last'][scalar])<1e-6,dict(raw=f[key],monitor=s['monitor_last'][scalar]))
        check(name+':independent_advected_energy',abs(f['advected_energy_W']-s['modeled_advected_energy_pickup_W'])<1e-4,f['advected_energy_W'])
        check(name+':mass',s['mass_imbalance_fraction']<=.001 and abs(f['ports']['inlet']['mass_kg_s']+.5)<=.0005,s['mass_imbalance_fraction'])
        q=s.get('energy_imbalance_with_inlet_diffusion_fraction')
        if q is None:checks.append(dict(check=name+':energy',status='not checked',evidence='No inlet diffusion correction'))
        else:check(name+':energy',q<=.01,q)
        check(name+':interface_pair',abs(s['monitor_last']['interfacePower']+s['monitor_last']['fluidPower'])/240<=.01,[s['monitor_last']['interfacePower'],s['monitor_last']['fluidPower']])
        check(name+':convergence_temperature',s['final_100_iteration_ranges']['heatedMax']<=.1,s['final_100_iteration_ranges']['heatedMax'])
        check(name+':convergence_pressure',s['pressure_drop_drift_fraction']<=.01,s['pressure_drop_drift_fraction'])
        residuals=s['last100_residual_max'];required={'fluid:Ux','fluid:Uy','fluid:Uz','fluid:p_rgh','fluid:h','fluid:k','fluid:epsilon','solid:h'}
        check(name+':residuals',required<=set(residuals) and all(v['initial']<=1e-5 and v['linear_final']<=1e-7 for v in residuals.values()),residuals)
        yp=s['yplus_face_count_distribution'];checks.append(dict(check=name+':wall_yplus',status='pass' if yp['fraction_below30']==0 and yp['fraction_above300']==0 else 'not checked',evidence=yp,note='Outside nominal30–300 requires explicit engineering review; not a hard adopted numerical threshold.'))
        check(name+':heated_temperature_limit',f['heated_max_K']<500,f['heated_max_K'])
        sat=saturation_temperature(f['pmin_absolute_Pa']);check(name+':single_phase_screen',sat-f['wetted_max_K']>=10,dict(required_margin_K=10,wetted_K=f['wetted_max_K'],minimum_absolute_pressure_Pa=f['pmin_absolute_Pa'],saturation_K=sat,margin_K=sat-f['wetted_max_K']))
        cases[name]={'summary':s,'independent_mesh':m,'independent_fields':f}
    a,b=[cases[n]['summary'] for n in names];ta,tb=[v['monitor_last']['heatedMax'] for v in (a,b)]
    check('paired_heated_max_difference',abs(ta-tb)<=1,abs(ta-tb))
    check('paired_heated_rise_difference',abs(ta-tb)/abs(tb-300)<=.05,abs(ta-tb)/abs(tb-300))
    check('paired_pressure_drop_difference',abs(a['pressure_drop_Pa']-b['pressure_drop_Pa'])/abs(b['pressure_drop_Pa'])<=.05,abs(a['pressure_drop_Pa']-b['pressure_drop_Pa'])/abs(b['pressure_drop_Pa']))
    return dict(scope='fixed demo numerical checks, not experimental validation',cases=cases,checks=checks,input_sha256=inputs,numerical_checks_pass=all(c['status']=='pass' for c in checks if not c['check'].endswith(':wall_yplus')),wall_model_manual_review_required=any(c['status']!='pass' for c in checks if c['check'].endswith(':wall_yplus')))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('coarse');p.add_argument('fine');p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();r=review(a.run,[a.coarse,a.fine]);a.output.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps({'numerical_checks_pass':r['numerical_checks_pass'],'checks':r['checks']},indent=2))

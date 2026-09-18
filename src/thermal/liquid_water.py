"""IAPWS SR6-08(2011) liquid-water correlations at 0.1 MPa.

Source: https://iapws.org/technical-guidance/release/LiquidWater.download
Equations 2,4,7,8; tables1,2,5,6. This is not a high-pressure property model.
Common implemented range273.15–383.15K; callers must review pressure validity.
"""
import math


def properties(temperature_K):
    t = float(temperature_K)
    if not math.isfinite(t) or not 273.15 <= t <= 383.15:
        raise ValueError('Liquid-water correlation common range: 273.15–383.15K')
    alpha, beta, tau = 10/(593-t), 10/(t-232), t/10
    r = 461.51805
    volume = r*10/100000*(.0193763157
        + sum(a*alpha**n for a,n in zip([6744.58446,-222521.604,100231247,-1635521180,8322996580],[4,5,7,8,9]))
        + sum(b*beta**m for b,m in zip([.00578545292,-.0153195665,.0311337859,-.0423546241,.0338713507,-.0119946761],[1,2,3,4,5,6])))
    cp = -r*(-8.983025854+tau*(
        sum(n*(n+1)*a*alpha**(n+2) for a,n in zip([-166147.0539,2708781.640,-155719154.4],[4,5,7]))
        + sum(m*(m+1)*b*beta**(m+2) for b,m in zip([-.8237426256,1.908956353,-2.017597384,.8546361348],[2,3,4,5]))))
    x = t/300
    return {'density_kg_m3':1/volume,'cp_J_kg_K':cp,
            'dynamic_viscosity_Pa_s':1e-6*sum(a*x**b for a,b in zip([280.68,511.45,61.131,.45903],[-1.9,-7.7,-19.6,-40])),
            'conductivity_W_m_K':sum(a*x**b for a,b in zip([1.663,-1.7781,1.1567,-.432115],[-1.15,-3.4,-6,-7.6]))}

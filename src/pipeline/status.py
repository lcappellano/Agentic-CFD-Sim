"""Result status levels. This is the single place their meaning is defined.

``diagnostic``            executed, but a numerical or model screen fails; numbers are not results.
``numerically_screened``  all numerical gates and the liquid-phase screen pass on one mesh;
                          mesh sensitivity, model applicability and an independent review remain.
``accepted``              a reviewer recorded an explicit acceptance decision (``decision.json``);
                          never set by code.
No level implies experimental validation.
"""

LEVELS = ('diagnostic', 'numerically_screened', 'accepted')

DESCRIPTIONS = {
    'diagnostic': 'Executed; a numerical or model screen fails. Values are diagnostic only.',
    'numerically_screened': 'Numerical gates and liquid-phase screen pass on a single mesh; review pending.',
    'accepted': 'Explicit reviewer acceptance recorded in decision.json.',
}


def case_status(manifest, review, last_chunk):
    """Status dictionary for a stopped case from its manifest and bounded review."""
    screened = (manifest.get('execution_status') == 'succeeded' and last_chunk['numerical_screen_pass']
                and last_chunk['phase_margin_screen_pass']
                and last_chunk['transport_validity'].get('within_declared_range') is not False)
    status = 'numerically_screened' if screened else 'diagnostic'
    return {'status': status, 'description': DESCRIPTIONS[status],
            'numerical_criteria': 'pass' if last_chunk['numerical_screen_pass'] else 'fail',
            'phase_screen': 'pass' if last_chunk['phase_margin_screen_pass'] else 'fail',
            'stop_reason': review.get('status'), 'iteration': last_chunk['iteration']}

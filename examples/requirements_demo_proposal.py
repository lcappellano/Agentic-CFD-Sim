"""Highlight proposals on the known synthetic through-bore fixture; never approve."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from requirements import review

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('review_directory')
args = parser.parse_args()
state = review.read_state(args.review_directory)
if state['model']['source']['name'] != 'cooling_block_through_bore_v1.step':
    raise ValueError('This proposal is only for the named synthetic test fixture.')
ports = sorted(state['model']['virtual_faces'], key=lambda item: item['centroid_mm'][0])
if len(ports) != 2:
    raise ValueError('Expected the two circular openings of the synthetic fixture.')
heated = max(state['model']['faces'], key=lambda item: item['centroid_mm'][2])
requirements = state['draft']['requirements']
requirements['title'] = 'DEMO: through-bore cooling block — unapproved proposals'
requirements['notes'] = ('Demonstration geometry only. Blue inlet, green outlet and orange '
                         'heated top are illustrative proposals, not user-confirmed conditions. '
                         'Physical values remain blank.')
result = review.save_draft(args.review_directory,
                          {'selections': {'inlet': [ports[0]['id']], 'outlet': [ports[1]['id']],
                                          'heated': [heated['id']]}, 'requirements': requirements},
                          state['draft']['revision'])
print('Saved synthetic display proposals. Approved:', result['approved'])

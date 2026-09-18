"""Browser integration test using a temporary synthetic review, never user approval."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.requirements import review
from src.requirements.server import make_server
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screenshot', required=True)
    args = parser.parse_args()
    model = json.loads((ROOT / 'src/cad/fixtures/cooling_block_through_bore_v1.preview.json').read_text())
    source = ROOT / 'src/cad/fixtures/cooling_block_through_bore_v1.step'
    with tempfile.TemporaryDirectory(prefix='cooling-browser-test-') as temporary:
        folder = Path(temporary)
        review.initialize_review(folder, source, model)
        server = make_server(folder, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as browser_tools:
                browser = browser_tools.chromium.launch(headless=True, args=[
                    '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
                page = browser.new_page(viewport={'width': 1440, 'height': 1080})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}')
                expect(page.locator('#viewer-placeholder')).to_be_hidden(timeout=20000)
                expect(page.locator('#viewport canvas')).to_be_visible()
                expect(page.locator('#approve')).to_be_disabled()
                expect(page.locator('#handoff')).to_be_disabled()
                expect(page.locator('#confirm-review')).not_to_be_checked()
                page.locator('[name="max_pump_pressure_rise"]').fill('8')
                page.locator('#atmospheric-return').click()
                expect(page.locator('[name="pressure_mode"]')).to_have_value('absolute')
                expect(page.locator('[name="pressure_min"]')).to_have_value('1.01325')
                expect(page.locator('[name="pressure_max"]')).to_have_value('1.01325')
                expect(page.locator('[name="max_pump_pressure_rise"]')).to_have_value('8')


                # Real ray picking, then orbit; check that the inspected CAD ID updates.
                page.locator('#viewport canvas').click(position={'x': 340, 'y': 245})
                expect(page.locator('#inspector')).to_contain_text('face:')
                canvas = page.locator('#viewport canvas')
                before = canvas.screenshot()
                box = canvas.bounding_box()
                page.mouse.move(box['x'] + 350, box['y'] + 250)
                page.mouse.down(button="middle")
                page.mouse.move(box['x'] + 430, box['y'] + 280, steps=12)
                page.mouse.up(button="middle")
                page.wait_for_timeout(300)
                assert canvas.screenshot() != before, 'Orbit interaction did not change rendered geometry'
                page.locator('#fit-view').click()
                page.locator('.face-browser summary').click()
                ports = sorted(model['virtual_faces'], key=lambda x: x['centroid_mm'][0])
                heated = max(model['faces'], key=lambda x: x['centroid_mm'][2])
                for role, identity in [('inlet', ports[0]['id']), ('outlet', ports[1]['id']), ('heated', heated['id'])]:
                    page.locator(f'[data-role="{role}"]').click()
                    page.locator(f'[data-face-id="{identity}"]').click()
                expect(page.locator('#selection-summary')).to_contain_text('Inlet · 1')
                expect(page.locator('#selection-summary')).to_contain_text('Outlet · 1')
                expect(page.locator('#selection-summary')).to_contain_text('Heat into solid · 1')
                page.locator('[data-role="heated"]').click()
                page.locator(f'[data-face-id="{ports[0]["id"]}"]').click()
                expect(page.locator('#message')).to_contain_text('cannot be a heated solid surface')
                # Solely test values: not an engineering recommendation or real review.
                values = {'title': 'SYNTHETIC UI TEST — not simulation inputs',
                          'solid_material': 'Test aluminium', 'coolant_material': 'Test water',
                          'inlet_temperature_K': '293.15', 'maximum_surface_temperature_K': '333.15',
                          'heat_value': '10000', 'other_thermal_boundaries': 'Test: adiabatic other walls',
                          'flow_min': '0.01', 'flow_max': '0.02', 'pressure_min': '0',
                          'pressure_max': '0.60005', 'objective': 'UI test only: feasibility'}
                for name, value in values.items():
                    page.locator(f'[name="{name}"]').fill(value)
                page.locator('[name="units_confirmed"]').check()
                page.locator('#save').click()
                expect(page.locator('#save-state')).to_have_text('Saved revision 1')
                expect(page.locator('#pressure_min-error')).to_contain_text('0 bar absolute')
                expect(page.locator('#confirm-review')).to_be_disabled()
                page.reload()
                expect(page.locator('#viewer-placeholder')).to_be_hidden()
                expect(page.locator('[name="pressure_min"]')).to_have_value('0')
                expect(page.locator('#pressure_min-error')).to_contain_text('greater than 0')
                page.locator('[name="pressure_mode"]').select_option('gauge')
                expect(page.locator('#pressure_reference-error')).to_contain_text('reference')
                expect(page.locator('#pressure_min-error')).to_be_hidden()
                page.locator('#save').click()
                expect(page.locator('#save-state')).to_have_text('Saved revision 2')
                expect(page.locator('#confirm-review')).to_be_disabled()
                page.locator('[name="pressure_reference"]').fill('1.01325')
                expect(page.locator('#pressure-conversion')).to_contain_text('1.01325–1.6133 bar')
                page.locator('#save').click()
                expect(page.locator('#save-state')).to_have_text('Saved revision 3')
                assert not review.read_state(folder)['issues']
                assert review.read_state(folder)['draft']['requirements']['outlet_absolute_pressure_bounds_Pa'] == [101325, 161330]
                page.reload()
                expect(page.locator('#viewer-placeholder')).to_be_hidden()
                expect(page.locator('[name="pressure_mode"]')).to_have_value('gauge')
                expect(page.locator('[name="pressure_min"]')).to_have_value('0')
                expect(page.locator('[name="pressure_reference"]')).to_have_value('1.01325')
                expect(page.locator('[name="pressure_max"]')).to_have_value('0.60005')
                expect(page.locator('#pressure_min-error')).to_be_hidden()
                expect(page.locator('[name="heat_value"]')).to_have_value('10000')
                expect(page.locator('#heated-area')).to_contain_text('Total applied heat: 24 W')
                expect(page.locator('#selection-summary')).to_contain_text('Heat into solid · 1')
                expect(page.locator('#confirm-review')).not_to_be_checked()
                # Show opposite port through translucent body for evidence capture.
                page.locator('#xray').check()
                page.locator('#reviewer').fill('Synthetic automated test only')
                expect(page.locator('#approve')).to_be_disabled()
                page.locator('#confirm-review').check()
                expect(page.locator('#approve')).to_be_enabled()
                screenshot = Path(args.screenshot)
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                page.evaluate('window.scrollTo(0, 0)')
                page.wait_for_timeout(200)
                page.screenshot(path=str(screenshot))
                page.locator('#approve').click()
                expect(page.locator('#review-status')).to_have_text('Approved for CAD')
                page.locator('#handoff').click()
                expect(page.locator('#handoff-result')).to_contain_text('CAD handoff created:')
                package = next((folder / 'handoffs').iterdir())
                assert review.verify_handoff(package)['valid']
                page.locator('[name="heat_value"]').fill('12000')
                expect(page.locator('#handoff')).to_be_disabled()
                page.locator('#save').click()
                expect(page.locator('#save-state')).to_have_text('Saved revision 4')
                assert not review.read_state(folder)['approved']
                expect(page.locator('#confirm-review')).not_to_be_checked()
                assert not errors, errors
                print(json.dumps({'status': 'passed', 'browser': browser.version,
                                  'checks': ['WebGL render', 'ray picking', 'orbit', 'face assignment',
                                             'saved zero absolute field error', 'explicit gauge reference',
                                             'gauge conversion persistence',
                                             'virtual cap heat rejection', 'draft persistence',
                                             'explicit confirmation', 'CAD handoff', 'edit invalidates approval'],
                                  'page_errors': errors, 'screenshot': str(screenshot),
                                  'scope': 'Temporary synthetic fixture only; no user review approved.'}, indent=2))
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    main()

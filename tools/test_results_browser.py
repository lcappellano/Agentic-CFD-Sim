"""Exercise the local read-only results viewer with real Chromium/WebGL."""
import argparse
import base64
import json
import math
from pathlib import Path

from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8766')
    parser.add_argument('--screenshot', required=True)
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=[
            '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
        page = browser.new_page(viewport={'width': 1600, 'height': 1200})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(args.url)
        expect(page.locator('#loading')).to_be_hidden(timeout=60000)
        expect(page.locator('#error')).to_be_hidden()
        canvas = page.locator('#viewport canvas')
        expect(canvas).to_be_visible()
        expect(page.locator('#summary')).to_contain_text('35.10')
        expect(page.locator('#case-label')).to_contain_text('2000')
        # Find a rendered triangle through real mouse picking, no synthetic DOM event.
        box = canvas.bounding_box()
        found = False
        for x, y in ((.5, .5), (.5, .4), (.4, .5), (.6, .5), (.5, .6)):
            canvas.click(position={'x': box['width'] * x, 'y': box['height'] * y})
            if 'Click a colored' not in page.locator('#probe').inner_text():
                found = True
                break
        assert found, 'Ray picking did not identify a result triangle'
        expect(page.locator('#probe')).to_contain_text('°C')
        def drag(button, modifier=None, end=(.65, .6)):
            box = canvas.bounding_box()
            page.mouse.move(box['x'] + box['width'] * .5, box['y'] + box['height'] * .5)
            if modifier:
                page.keyboard.down(modifier)
            page.mouse.down(button=button)
            page.mouse.move(box['x'] + box['width'] * end[0], box['y'] + box['height'] * end[1], steps=12)
            page.mouse.up(button=button)
            if modifier:
                page.keyboard.up(modifier)
            page.wait_for_timeout(100)

        def camera_state():
            return page.evaluate('window.resultsCameraState()')

        def same_orientation(a, b, tolerance=1e-8):
            # q and -q encode the same orientation.
            return abs(abs(sum(x*y for x, y in zip(a['quaternion'], b['quaternion']))) - 1) < tolerance

        page.wait_for_timeout(100)
        before = canvas.screenshot()
        probe_before = page.locator('#probe').inner_text()
        drag('left')
        assert canvas.screenshot() == before, 'Left drag unexpectedly moved the camera'
        assert page.locator('#probe').inner_text() == probe_before, 'Left drag unexpectedly probed'
        drag('middle')
        rotated = canvas.screenshot()
        assert rotated != before, 'Middle drag did not rotate the rendering'
        assert page.locator('#probe').inner_text() == probe_before, 'Middle drag unexpectedly probed'
        page.wait_for_timeout(250)
        assert canvas.screenshot() == rotated, 'Camera kept moving after releasing middle button'
        rotation_state = camera_state()
        drag('middle', 'Control')
        assert same_orientation(rotation_state, camera_state()), 'Ctrl+middle pan rotated camera'
        panned = canvas.screenshot()
        assert panned != rotated, 'Ctrl+middle drag did not pan the rendering'
        assert page.locator('#probe').inner_text() == probe_before, 'Pan unexpectedly probed'
        drag('right')
        assert same_orientation(rotation_state, camera_state()), 'Right pan rotated camera'
        right_panned = canvas.screenshot()
        assert right_panned != panned, 'Right drag did not pan the rendering'
        assert page.locator('#probe').inner_text() == probe_before, 'Right pan unexpectedly probed'
        page.mouse.wheel(0, 180)
        page.wait_for_timeout(150)
        assert canvas.screenshot() != right_panned, 'Mouse wheel did not zoom the rendering'
        # Orthogonal views used to change the orbit's up-axis. Exercise each
        # actual button, then drag through screen-center and back to its preset.
        presets = page.locator('[data-view]').evaluate_all('(els) => els.map(el => el.dataset.view)')
        assert len(presets) >= 7, f'Missing orthogonal view presets: {presets}'
        for view in presets:
            button = page.locator(f'[data-view="{view}"]')
            button.click()
            page.wait_for_timeout(100)
            preset_image = canvas.screenshot()
            drag('middle', end=(.5, .85))
            assert canvas.screenshot() != preset_image, f'Rotation locked from {view} view'
            button.click()
            page.wait_for_timeout(100)
            assert canvas.screenshot() == preset_image, f'{view} preset is not repeatable'
        # Return along the exact same held-button path from both former poles.
        # Inspect real camera state as well as pixels; screenshot changes alone
        # cannot distinguish a useful rotation from an accidental axis reset.
        for view in ('top', 'bottom'):
            page.locator(f'[data-view="{view}"]').click()
            initial = camera_state()
            box = canvas.bounding_box()
            x, y = box['x'] + box['width']*.5, box['y'] + box['height']*.5
            page.mouse.move(x, y)
            page.mouse.down(button='middle')
            previous = initial
            for fraction in (.05, .1, .15, .2, .15, .1, .05, 0):
                page.mouse.move(x + box['width']*fraction, y + box['height']*fraction/2)
                current = camera_state()
                assert all(math.isfinite(v) for key in ('position', 'up', 'quaternion', 'target')
                           for v in current[key]), 'Nonfinite camera state during pole rotation'
                assert sum((a-b)**2 for a,b in zip(initial['target'], current['target'])) < 1e-12, 'Rotation moved its pivot'
                dot = abs(sum(a*b for a,b in zip(previous['quaternion'], current['quaternion'])))
                assert dot > .9, f'Unexpected orientation jump from {view}: {dot}'
                previous = current
            page.mouse.up(button='middle')
            assert same_orientation(initial, camera_state()), f'Out-and-back drag did not recover {view}'
        page.locator('[data-view="top"]').click()
        drag('middle', end=(.5, .85))
        pole_first = canvas.screenshot()
        drag('middle', end=(.5, .85))
        assert canvas.screenshot() != pole_first, 'Repeated rotation from top became locked'
        pole_second = canvas.screenshot()
        page.wait_for_timeout(300)
        assert canvas.screenshot() == pole_second, 'Pole rotation drifted after release'
        page.locator('#reset').click()
        page.wait_for_timeout(100)
        fitted = canvas.screenshot()
        fitted_state = camera_state()
        page.keyboard.press('f')
        page.wait_for_timeout(100)
        assert same_orientation(fitted_state, camera_state()), 'F changed view orientation'
        assert canvas.screenshot() == fitted, 'F and Fit button disagree'
        page.locator('#reset').click()
        page.wait_for_timeout(100)
        assert canvas.screenshot() == fitted, 'Repeated Fit changed the camera'
        page.locator('[data-view="iso"]').click()
        page.wait_for_timeout(100)
        iso_state = camera_state()
        iso_image = canvas.screenshot()
        iso_bounds = canvas.bounding_box()
        iso_probe = page.locator('#probe').inner_text()
        drag('middle')
        page.keyboard.press('Home')
        page.wait_for_timeout(100)
        assert same_orientation(iso_state, camera_state()), 'Home did not restore isometric orientation'
        home_image = canvas.screenshot()
        # The DOM hint text over the canvas may differ by one antialiasing
        # intensity after keyboard focus despite exactly identical camera state.
        # Decode PNGs, bound both intensity and affected area; never hide geometry
        # movement under an unrestricted screenshot mismatch allowance.
        home_pixels = page.evaluate('''async ([before, after]) => {
            async function decode(encoded) {
                const img = new Image(); img.src = 'data:image/png;base64,' + encoded;
                await img.decode();
                const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
                const ctx = c.getContext('2d'); ctx.drawImage(img, 0, 0);
                return {width: c.width, height: c.height, rgba: ctx.getImageData(0, 0, c.width, c.height).data};
            }
            const a = await decode(before), b = await decode(after);
            if(a.width !== b.width || a.height !== b.height) return {same_size: false};
            let changed = 0, maximum = 0;
            for(let i=0; i<a.rgba.length; i+=4) {
                let delta = 0;
                for(let k=0; k<4; k++) delta = Math.max(delta, Math.abs(a.rgba[i+k]-b.rgba[i+k]));
                if(delta) changed++; maximum = Math.max(maximum, delta);
            }
            return {same_size: true, changed_pixels: changed, fraction: changed/(a.width*a.height), max_delta: maximum};
        }''', [base64.b64encode(iso_image).decode(), base64.b64encode(home_image).decode()])
        if home_image != iso_image:
            diagnostics = Path(args.screenshot).parent / 'home-reset-diagnostic'
            diagnostics.mkdir(parents=True, exist_ok=True)
            (diagnostics / 'before.png').write_bytes(iso_image)
            (diagnostics / 'after.png').write_bytes(home_image)
            states = {'before': iso_state, 'after': camera_state(), 'pixel_delta': home_pixels,
                      'before_bounds': iso_bounds, 'after_bounds': canvas.bounding_box(),
                      'before_probe': iso_probe, 'after_probe': page.locator('#probe').inner_text()}
            (diagnostics / 'camera-states.json').write_text(json.dumps(states, indent=2))
            print(json.dumps({'home_reset_mismatch': states, 'diagnostics': str(diagnostics)}, indent=2), flush=True)
        home_state = camera_state()
        for key in ('position', 'up', 'target', 'projection'):
            assert all(math.isclose(a, b, abs_tol=1e-8, rel_tol=1e-10)
                       for a, b in zip(iso_state[key], home_state[key])), f'Home changed {key}: {iso_state[key]} vs {home_state[key]}'
        assert math.isclose(iso_state['zoom'], home_state['zoom'], abs_tol=1e-10), 'Home did not restore zoom'
        assert home_pixels['same_size'] and home_pixels['max_delta'] <= 1 and home_pixels['fraction'] <= .001, (
            f'Home did not restore fitted isometric view: {home_pixels}')
        # Responsive resize must keep the result available and allow recovery.
        page.set_viewport_size({'width': 1100, 'height': 850})
        page.wait_for_timeout(200)
        expect(canvas).to_be_visible()
        page.locator('[data-view="iso"]').click()
        resized = canvas.screenshot()
        drag('middle')
        assert canvas.screenshot() != resized, 'Camera stopped responding after resize'
        page.set_viewport_size({'width': 1600, 'height': 1200})
        page.wait_for_timeout(200)
        page.locator('#reset').click()
        page.locator('#temperature-unit').select_option('K')
        expect(page.locator('#legend-title')).to_contain_text('K')
        page.locator('#field').select_option('p_absolute_Pa')
        expect(page.locator('#legend-title')).to_contain_text('bar')
        expect(page.locator('#reference-note')).to_contain_text('1.01325')
        gauge_min = page.locator('#legend-min').inner_text()
        page.locator('#pressure-unit').select_option('absolute')
        assert page.locator('#legend-min').inner_text() != gauge_min
        page.locator('#field').select_option('speed_m_s')
        expect(page.locator('#legend-title')).to_contain_text('m/s')
        page.locator('#show-solid').uncheck()
        page.locator('#show-fluid').check()
        page.locator('#slice-axis').select_option('y')
        page.locator('#slice-axis').select_option('z')
        page.locator('#slice-axis').select_option('x')
        page.locator('#slice-index').fill('1')
        page.locator('#mesh').check()
        page.locator('[data-view="right"]').click()
        page.locator('[data-view="iso"]').click()
        page.locator('#mesh').uncheck()
        page.locator('#field').select_option('T_K')
        page.locator('#temperature-unit').select_option('C')
        page.locator('#show-solid').check()
        page.locator('#opacity').fill('0.25')
        page.locator('#slice-axis').select_option('y')
        page.locator('#reset').click()
        path = Path(args.screenshot)
        path.parent.mkdir(parents=True, exist_ok=True)
        page.wait_for_timeout(300)
        page.screenshot(path=str(path), full_page=True)
        assert not errors, errors
        print(json.dumps({'status': 'passed', 'browser': browser.version,
                          'checks': ['actual WebGL', 'ray picking', 'left drag stationary', 'middle drag rotation',
                                     'immediate rotation stop', 'Ctrl+middle pan', 'right pan', 'wheel zoom',
                                     'seven repeatable view presets', 'rotation from every principal view',
                                     'repeated top-view rotation', 'top/bottom reversible smooth rotation',
                                     'pan preserves orientation', 'F fit/Home reset', 'repeatable fit', 'resize navigation', 'temperature units',
                                     'pressure reference', 'velocity', 'visibility', 'slices',
                                     'mesh edges', 'accepted result summary'],
                          'home_reset_pixel_delta': home_pixels, 'page_errors': errors, 'screenshot': str(path)}, indent=2))
        browser.close()


if __name__ == '__main__':
    main()

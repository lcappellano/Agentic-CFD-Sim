"""Check a saved-case viewer loads, probes and rotates without rerunning CFD."""
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright, expect


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True);parser.add_argument('--case',required=True)
    parser.add_argument('--screenshot',type=Path,required=True)
    args=parser.parse_args()
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader'])
        page=browser.new_page(viewport={'width':1600,'height':1100});errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(args.url,wait_until='domcontentloaded')
        expect(page.locator('#loading')).to_be_hidden(timeout=180000)
        expect(page.locator('#case-label')).to_contain_text(args.case)
        expect(page.locator('#summary')).to_contain_text('Copper maximum')
        expect(page.locator('#error')).to_be_hidden()
        canvas=page.locator('#viewport canvas');box=canvas.bounding_box()
        before=page.evaluate('window.resultsCameraState()')
        page.mouse.move(box['x']+box['width']*.5,box['y']+box['height']*.5)
        page.mouse.down(button='middle');page.mouse.move(box['x']+box['width']*.6,box['y']+box['height']*.55,steps=5);page.mouse.up(button='middle')
        after=page.evaluate('window.resultsCameraState()')
        assert before['quaternion']!=after['quaternion'],'Middle drag did not rotate'
        page.locator('[data-view="back"]').click()
        canvas.click(position={'x':box['width']*.5,'y':box['height']*.5})
        expect(page.locator('#probe')).to_contain_text('°C')
        page.select_option('#field','p_absolute_Pa')
        expect(page.locator('#field-title')).to_contain_text('bar absolute')
        page.select_option('#field','T_K')
        page.locator('[data-view="iso"]').click()
        args.screenshot.parent.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(args.screenshot),full_page=True)
        assert not errors,errors
        print('Saved-case viewer load, temperature summary, middle rotation, probing and pressure display passed.')
        browser.close()

if __name__=='__main__':main()

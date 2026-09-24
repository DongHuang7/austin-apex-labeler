"""Generate the three-design gallery; reference photos are local preview assets only."""
from pathlib import Path
import sys
from html import escape
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from mailer.templates import LISTING_LAYOUTS, LISTING_LAYOUT_DESCRIPTIONS, build_listing_email

out = Path(__file__).resolve().parents[2] / 'previews'
out.mkdir(exist_ok=True)
listing = dict(UnparsedAddress='123 Example Lane', City='Austin', StateOrProvince='TX',
               PostalCode='78704', ListPrice=825000, BedroomsTotal=4,
               BathroomsTotalInteger=3, LivingArea=2450,
               PublicRemarks='A place to slow down. A home to make your own.\n\nLight-filled interiors open onto generous outdoor spaces, creating room for quiet mornings and evenings with friends.\n\nSPACE TO GATHER\nAn open living area connects to the kitchen and covered patio. Four bedrooms offer flexibility for everyday life.\n\nThis is illustrative copy. Live campaigns use the selected MLS listing’s actual description.')
photos = [f'https://example.com/reference-photo-{i}.jpg' for i in range(1, 6)]
extra = dict(listing=dict(listing, UnparsedAddress='456 Sample Terrace', ListPrice=695000,
                         BedroomsTotal=3, BathroomsTotalInteger=2, LivingArea=1980),
             photo_urls=[photos[3]], description='A second illustrative property in the collection. Each selected MLS listing has its own photograph, facts, description, and details link.',
             property_url='https://www.austinapexre.com', email_type='just_listed')
cards=[]
for number, (key, name) in enumerate(LISTING_LAYOUTS.items(), 1):
    _, html = build_listing_email(listing, layout=key, photo_urls=photos,
                                 collection_entries=[extra] if key == 'listing_collection' else None)
    for i, url in enumerate(photos, 1):
        asset = out / f'reference-photo-{i}.jpg'
        if asset.exists():
            html = html.replace(url, asset.name)
        else:
            placeholder = f'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400"><rect width="600" height="400" fill="#dce4e0"/><text x="300" y="200" text-anchor="middle" font-family="Arial" font-size="20" fill="#264653">MLS property photograph</text></svg>'
            (out/'placeholder.svg').write_text(placeholder)
            html = html.replace(url, 'placeholder.svg')
    (out/f'{key}.html').write_text(html)
    cards.append(f'''<article><div class="card-heading"><span class="number">0{number}</span><h2>{name}</h2><p>{LISTING_LAYOUT_DESCRIPTIONS[key]}</p><a href="{key}.html">Open full email ↗</a></div><div class="viewport"><iframe title="{name}" src="{key}.html" scrolling="no"></iframe></div></article>''')
(out/'index.html').write_text('''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Three MLS campaign designs · Austin Apex</title><style>
*{box-sizing:border-box}body{margin:0;background:#f2f1ed;color:#203e49;font-family:Arial,sans-serif}header{max-width:1440px;margin:auto;padding:48px 32px 32px}.eyebrow{font-size:11px;letter-spacing:3px;font-weight:bold}h1{font:46px Georgia,serif;line-height:1.15;margin:18px 0}header p{max-width:770px;font-size:15px;line-height:1.7;color:#5d6e70}.controls{display:flex;gap:8px;margin-top:24px}button{font:13px Arial,sans-serif;cursor:pointer;padding:12px 20px;border:1px solid #203e49;background:transparent;color:#203e49;border-radius:4px}button[aria-pressed=true]{background:#203e49;color:white}button:focus-visible,a:focus-visible{outline:3px solid #739d95;outline-offset:4px}main{max-width:1440px;margin:auto;padding:0 32px 48px;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:22px}article{background:white;border:1px solid #d8ddd7;border-radius:8px;overflow:hidden;min-width:0}.card-heading{padding:24px;min-height:230px}.number{font-size:11px;letter-spacing:2px;color:#73827b}h2{font:26px Georgia,serif;margin:12px 0}article p{font-size:13px;line-height:1.7;color:#62716d;min-height:66px}a{font-size:12px;font-weight:bold;color:#203e49;text-underline-offset:4px}.viewport{height:1120px;overflow:hidden;background:#f9f9f9;position:relative;border-top:1px solid #e5e7e2}iframe{border:0;width:640px;height:2800px;position:absolute;top:0;left:0;transform-origin:top left}footer{max-width:1440px;margin:auto;padding:0 32px 40px;font-size:12px;line-height:1.7;color:#62716d}footer a{font-weight:normal}@media(max-width:950px){main{grid-template-columns:1fr;max-width:680px}.card-heading{min-height:0}.viewport{height:1100px}h1{font-size:34px}}
</style></head><body><header><div class="eyebrow">AUSTIN APEX / EMAIL COLLECTION</div><h1>Three designs. Three different stories.</h1><p>A detailed property showcase, an editorial spotlight, and a curated listing collection. Each uses the same MLS facts, with a different reading experience.</p><div class="controls" aria-label="Preview width"><button type="button" aria-pressed="true" data-width="640">Desktop</button><button type="button" aria-pressed="false" data-width="375">Mobile</button></div></header><main>'''+''.join(cards)+'''</main><footer>Preview only: addresses, prices, and descriptions are illustrative. Property photos are from your <a href="https://www.compass.com/notifications/emails/70d573c8-b895-4d41-b3e5-f3a4680c1b6c.html">second Compass reference</a> for this local design review; live campaigns use your selected MLS photos.</footer><script>
let width=640;
function resize(){document.querySelectorAll('.viewport').forEach(box=>{const frame=box.querySelector('iframe');const scale=Math.min(1,box.clientWidth/width);frame.style.width=width+'px';frame.style.transform='scale('+scale+')';frame.style.left=Math.max(0,(box.clientWidth-width*scale)/2)+'px';});}
document.querySelectorAll('button[data-width]').forEach(button=>button.addEventListener('click',()=>{width=Number(button.dataset.width);document.querySelectorAll('button[data-width]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));resize();}));
new ResizeObserver(resize).observe(document.querySelector('main'));resize();
</script></body></html>''')
# Retire only generated previews from the prior six-design gallery.
for old in ('original', 'feature_spotlight', 'featured_highlight', 'editorial', 'photo_gallery', 'property_brief'):
    (out/f'{old}.html').unlink(missing_ok=True)
print(out/'index.html')

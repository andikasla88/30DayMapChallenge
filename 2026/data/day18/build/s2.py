"""Day 18 (NULL): a Sentinel-2 look at SVY21 (0, 0). Reads only a small window of each cloud-optimised GeoTIFF.

Requires python 3.10+ with: rasterio numpy pyproj
usage: python -I s2.py <raw-dir>       (after fetch.py, which saved the STAC search to <raw-dir>/s2/search.json)

Picks the most recent Sentinel-2 L2A scene (Element 84 Earth Search, from the Copernicus Sentinel-2 archive on
AWS open data) whose scene classification layer shows (almost) no cloud, cirrus or cloud shadow within 6 km of the
point, then saves, for a 13.2 km x 13.2 km window around it, reprojected to WGS 84 (EPSG:4326):
  s2/visual.tif   true colour (the TCI product, 10 m)
  s2/nir.tif      near infrared, band 8 (10 m, reflectance x 10000), used by process.py to count ships
  s2/scl.tif      scene classification (20 m), resampled nearest
  s2/scene.json   the scene id, time, and the window.
"""
import json
import os
import sys

import numpy as np
import rasterio
from rasterio.warp import Resampling, calculate_default_transform, reproject, transform_bounds
from rasterio.windows import from_bounds
from pyproj import Transformer

RAW = sys.argv[1]
S2 = os.path.join(RAW, 's2')
os.environ.update(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif', GDAL_HTTP_MAX_RETRY='4', GDAL_HTTP_RETRY_DELAY='5')
LON, LAT = Transformer.from_crs('EPSG:3414', 'EPSG:4326', always_xy=True).transform(0, 0)
HALF = 0.06                   # degrees: the saved window is 0.12 deg (13.2 km) square
CLEAR_KM = 6.0                # no cloud allowed within this distance of the point
items = json.load(open(os.path.join(S2, 'search.json'), encoding='utf-8'))['features']
items.sort(key=lambda f: f['properties']['datetime'], reverse=True)
BOX = (LON - HALF, LAT - HALF, LON + HALF, LAT + HALF)


def window_read(href, box, out_shape=None, resampling=Resampling.nearest):
    with rasterio.open(href) as src:
        b = transform_bounds('EPSG:4326', src.crs, *box, densify_pts=21)
        win = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
        data = src.read(window=win, out_shape=out_shape and (src.count, *out_shape), resampling=resampling, boundless=True, fill_value=0)
        return data, src.window_transform(win), src.crs


chosen = None
for f in items[:40]:
    a = f['assets']
    try:
        scl, tr, crs = window_read(a['scl']['href'], BOX)
    except rasterio.errors.RasterioIOError as e:
        print('skip', f['id'], e)
        continue
    scl = scl[0]
    h, w = scl.shape
    yy, xx = np.mgrid[0:h, 0:w]
    cx, cy = (w - 1) / 2, (h - 1) / 2
    near = np.hypot((xx - cx) * 20, (yy - cy) * 20) <= CLEAR_KM * 1000
    bad = np.isin(scl, [0, 3, 8, 9, 10]) & near   # no data, cloud shadow, cloud (medium, high), cirrus
    frac = bad.sum() / near.sum()
    print(f['id'], f['properties']['datetime'][:10], 'scene cloud', f['properties'].get('eo:cloud_cover'), 'near-point bad', round(100 * frac, 2), '%')
    if frac < 0.001:   # under 0.1%: a few pixels, which can be ships the classifier took for cloud
        chosen = f
        break
if not chosen:
    raise SystemExit('no clear scene found')


def warp_to_4326(href, name, resampling, res):
    with rasterio.open(href) as src:
        b = transform_bounds('EPSG:4326', src.crs, *BOX, densify_pts=21)
        win = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
        data = src.read(window=win, boundless=True, fill_value=0)
        st = src.window_transform(win)
        width = height = int(round(2 * HALF / res))
        dst_t = rasterio.transform.from_bounds(*BOX, width, height)
        out = np.zeros((src.count, height, width), dtype=data.dtype)
        reproject(data, out, src_transform=st, src_crs=src.crs, dst_transform=dst_t, dst_crs='EPSG:4326', resampling=resampling)
        prof = dict(driver='GTiff', width=width, height=height, count=src.count, dtype=data.dtype, crs='EPSG:4326', transform=dst_t, compress='deflate')
        with rasterio.open(os.path.join(S2, name), 'w', **prof) as dst:
            dst.write(out)
    print('wrote', name, out.shape)


RES = 1e-4   # degrees per pixel, about 11 m: close to the native 10 m
a = chosen['assets']
warp_to_4326(a['visual']['href'], 'visual.tif', Resampling.bilinear, RES)
warp_to_4326(a['nir']['href'], 'nir.tif', Resampling.bilinear, RES)
warp_to_4326(a['scl']['href'], 'scl.tif', Resampling.nearest, RES)
json.dump({'id': chosen['id'], 'datetime': chosen['properties']['datetime'], 'platform': chosen['properties'].get('platform'),
           'scene_cloud_cover': chosen['properties'].get('eo:cloud_cover'), 'bounds': BOX, 'res_deg': RES,
           'stac': f"https://earth-search.aws.element84.com/v1/collections/sentinel-2-l2a/items/{chosen['id']}"},
          open(os.path.join(S2, 'scene.json'), 'w'), indent=1)
print('scene', chosen['id'], chosen['properties']['datetime'])

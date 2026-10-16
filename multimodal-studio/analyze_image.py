from PIL import Image
import numpy as np
from collections import Counter

img = Image.open('screenshot_2026-10-16.png')
arr = np.array(img)
print('Shape:', arr.shape)
print('Dtype:', arr.dtype)

# Get unique colors count
unique_colors = len(np.unique(arr.reshape(-1, arr.shape[-1]), axis=0))
print('Unique colors:', unique_colors)

# Get average color
avg = arr.mean(axis=(0,1))
print('Average RGBA:', avg)

# Get dominant colors by sampling
flat = arr.reshape(-1, 4)
sample = flat[::10]
counts = Counter(tuple(c) for c in sample)
top = counts.most_common(20)
print('\nTop 20 colors (sampled):')
for color, count in top:
    print('  RGBA{}: {}'.format(color, count))

# Analyze horizontal bands to understand layout
h, w = arr.shape[:2]
band_height = h // 5
for i in range(5):
    band = arr[i*band_height:(i+1)*band_height, :, :]
    band_avg = band.mean(axis=(0,1))
    band_unique = len(np.unique(band.reshape(-1, band.shape[-1]), axis=0))
    print('Band {} (y={}-{}): avg RGBA={}, unique colors={}'.format(
        i, i*band_height, (i+1)*band_height, band_avg.astype(int), band_unique))

# Check for text-like patterns (high contrast horizontal edges)
gray = np.array(img.convert('L'))
edges = np.abs(np.diff(gray, axis=1)).mean(axis=0)
print('\nHorizontal edge density per column (first 20):', edges[:20].astype(int))
print('Horizontal edge density per column (last 20):', edges[-20:].astype(int))
print('Max edge density:', edges.max())
print('Mean edge density:', edges.mean())

# Look for bright/text regions
bright_mask = gray > 200
bright_pct = bright_mask.sum() / bright_mask.size * 100
print('Bright pixels (>200): {:.1f}%'.format(bright_pct))

dark_mask = gray < 50
dark_pct = dark_mask.sum() / dark_mask.size * 100
print('Dark pixels (<50): {:.1f}%'.format(dark_pct))

# Check if it's a browser or app
top_100 = gray[:100, :]
top_avg = top_100.mean()
print('\nTop 100px avg brightness:', top_avg)

bottom_100 = gray[-100:, :]
bottom_avg = bottom_100.mean()
print('Bottom 100px avg brightness:', bottom_avg)

left_100 = gray[:, :100]
left_avg = left_100.mean()
print('Left 100px avg brightness:', left_avg)

right_100 = gray[:, -100:]
right_avg = right_100.mean()
print('Right 100px avg brightness:', right_avg)

# Check top-left corner
tl = gray[:50, :200]
tl_avg = tl.mean()
print('\nTop-left corner (50x200) avg brightness:', tl_avg)

# Top strip for browser URL bar
top_strip = gray[10:40, :]
top_strip_std = top_strip.std()
print('Top strip std dev:', top_strip_std)

# Save analysis results
with open('image_analysis.txt', 'w') as f:
    f.write('Image Analysis Results\n')
    f.write('======================\n')
    f.write('Format: PNG\n')
    f.write('Size: {}\n'.format(img.size))
    f.write('Mode: {}\n'.format(img.mode))
    f.write('Unique colors: {}\n'.format(unique_colors))
    f.write('Average RGBA: {}\n'.format(avg))
    f.write('Bright pixels (>200): {:.1f}%\n'.format(bright_pct))
    f.write('Dark pixels (<50): {:.1f}%\n'.format(dark_pct))
    f.write('Top 100px avg brightness: {:.1f}\n'.format(top_avg))
    f.write('Bottom 100px avg brightness: {:.1f}\n'.format(bottom_avg))
    f.write('Left 100px avg brightness: {:.1f}\n'.format(left_avg))
    f.write('Right 100px avg brightness: {:.1f}\n'.format(right_avg))

print('\nAnalysis saved to image_analysis.txt')
